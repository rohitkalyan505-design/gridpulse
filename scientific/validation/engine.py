"""
GridPulse — Telemetry Validation Engine
Executes Phase 2 Step 2: Data Validation & Electrical Ingestion Rules.

Locked Pipeline:
Raw Electrical Telemetry
→ Schema Validation
→ Timestamp Validation
→ Unit Validation
→ Range Validation
→ Missing Data Detection
→ Duplicate Detection
→ Flatline Detection
→ Quality Classification
→ Validated Telemetry
"""

from collections import defaultdict
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from scientific.contracts.asset import TransformerAssetSpec
from scientific.contracts.enums import (
    EvidenceClassification,
    IssueSeverity,
    MeasurementQuality,
)
from scientific.contracts.issues import (
    ContractViolationError,
    PhysicalBoundaryError,
    ProcessingIssue,
    TelemetryValidationError,
)
from scientific.contracts.measurement import Measurement
from scientific.contracts.results import ValidationSummary
from scientific.ingestion.contracts import (
    RawTelemetryBatch,
    RawTelemetryReading,
    RawTelemetryRecord,
)
from scientific.validation.contracts import (
    ValidatedTelemetryBatch,
    ValidatedTelemetryRecord,
)
from scientific.validation.rules import (
    ALLOWED_UNITS_BY_TYPE,
    CHANNEL_TAG_ALIASES,
    DEFAULT_FLATLINE_THRESHOLDS,
    DEFAULT_SANITY_LIMITS,
    FlatlineThreshold,
    GenericSanityLimits,
    MeasurementType,
    ValidationConfig,
)


class TelemetryValidator:
    """
    Deterministic electrical telemetry validation engine.
    Screens raw telemetry for structural, temporal, physical, and consistency validity
    before telemetry can reach downstream electrical calculations.
    """

    def __init__(
        self,
        config: Optional[ValidationConfig] = None,
        asset_spec: Optional[TransformerAssetSpec] = None,
    ) -> None:
        self.config = config or ValidationConfig()
        self.asset_spec = asset_spec

    def validate_batch(
        self,
        batch: RawTelemetryBatch,
    ) -> Tuple[ValidatedTelemetryBatch, List[ProcessingIssue]]:
        """
        Validates an entire RawTelemetryBatch and returns a ValidatedTelemetryBatch
        along with the complete list of structured ProcessingIssue records.
        """
        issues: List[ProcessingIssue] = []

        # 1. Schema Validation on Batch Header
        if not batch.asset_id or not batch.asset_id.strip():
            issue = ProcessingIssue(
                stage="validation",
                severity=IssueSeverity.CRITICAL,
                code="ERR_MISSING_ASSET_ID",
                message="Telemetry batch is missing a valid asset_id.",
            )
            issues.append(issue)
            if self.config.strict_mode:
                raise TelemetryValidationError(issue.message)
            return self._empty_batch(batch.asset_id or "UNKNOWN", issues)

        if self.asset_spec and self.asset_spec.asset_id != batch.asset_id:
            issue = ProcessingIssue(
                stage="validation",
                severity=IssueSeverity.CRITICAL,
                code="ERR_ASSET_ID_MISMATCH",
                message=f"Batch asset_id '{batch.asset_id}' does not match asset_spec id '{self.asset_spec.asset_id}'.",
                field_name="asset_id",
            )
            issues.append(issue)
            if self.config.strict_mode:
                raise TelemetryValidationError(issue.message)

        if not batch.records:
            issue = ProcessingIssue(
                stage="validation",
                severity=IssueSeverity.WARNING,
                code="WARN_EMPTY_BATCH",
                message=f"Telemetry batch for asset '{batch.asset_id}' contains zero records.",
            )
            issues.append(issue)
            return self._empty_batch(batch.asset_id, issues)

        # 2. Timestamp Validation: Check Temporal Ordering & Monotonicity
        is_monotonically_ordered = True
        last_ts: Optional[datetime] = None
        for r_idx, rec in enumerate(batch.records):
            if rec.timestamp.tzinfo is None:
                issue = ProcessingIssue(
                    stage="validation",
                    severity=IssueSeverity.CRITICAL,
                    code="ERR_TIMESTAMP_NAIVE",
                    message=f"Record at index {r_idx} has timezone-naive timestamp '{rec.timestamp}'.",
                    field_name="timestamp",
                )
                issues.append(issue)
                if self.config.strict_mode:
                    raise TelemetryValidationError(issue.message)

            if last_ts is not None:
                if rec.timestamp < last_ts:
                    is_monotonically_ordered = False
                    issues.append(
                        ProcessingIssue(
                            stage="validation",
                            severity=IssueSeverity.WARNING,
                            code="WARN_TIMESTAMP_OUT_OF_ORDER",
                            message=f"Record at index {r_idx} has timestamp {rec.timestamp} preceding earlier timestamp {last_ts}.",
                            field_name="timestamp",
                        )
                    )
            last_ts = rec.timestamp

        # 3. Duplicate Detection Across Entire Batch
        # Key: (asset_id, measurement_type, timestamp, sensor_id)
        readings_by_key: Dict[Tuple[str, MeasurementType, datetime, Optional[str]], List[RawTelemetryReading]] = (
            defaultdict(list)
        )
        conflicting_keys: Set[Tuple[str, MeasurementType, datetime, Optional[str]]] = set()

        for rec in batch.records:
            for reading in rec.readings:
                norm_type = self._resolve_channel_type(reading.channel_tag)
                if norm_type is not None:
                    key = (rec.asset_id, norm_type, reading.timestamp, reading.sensor_id)
                    readings_by_key[key].append(reading)

        for key, r_list in readings_by_key.items():
            if len(r_list) > 1:
                # Check if identical or conflicting
                vals = [r.raw_value for r in r_list if r.raw_value is not None]
                if len(set(vals)) > 1:
                    # Conflicting duplicate
                    conflicting_keys.add(key)
                    issues.append(
                        ProcessingIssue(
                            stage="validation",
                            severity=IssueSeverity.WARNING,
                            code="WARN_DUPLICATE_CONFLICTING",
                            message=(
                                f"Conflicting duplicate readings for channel {key[1].value} at {key[2].isoformat()}: "
                                f"values={[r.raw_value for r in r_list]}. Flagged as SUSPECT."
                            ),
                            field_name=key[1].value,
                        )
                    )
                else:
                    # Identical duplicate: preserve provenance trace
                    issues.append(
                        ProcessingIssue(
                            stage="validation",
                            severity=IssueSeverity.INFO,
                            code="INFO_DUPLICATE_IDENTICAL",
                            message=(
                                f"Identical duplicate detected for channel {key[1].value} at {key[2].isoformat()} "
                                f"({len(r_list)} copies with value {vals[0] if vals else None}). Deduplicated cleanly."
                            ),
                            field_name=key[1].value,
                        )
                    )

        # 4. Flatline Detection State Tracker
        # Tracks consecutive non-null values for each (asset_id, measurement_type, sensor_id)
        flatline_history: Dict[Tuple[str, MeasurementType, Optional[str]], List[float]] = defaultdict(list)
        flatline_flagged_keys: Set[Tuple[str, MeasurementType, datetime, Optional[str]]] = set()

        # Sort records by timestamp for chronological flatline evaluation
        sorted_records = sorted(batch.records, key=lambda r: r.timestamp)

        for rec in sorted_records:
            for reading in rec.readings:
                norm_type = self._resolve_channel_type(reading.channel_tag)
                if norm_type is None or reading.raw_value is None:
                    continue

                hist_key = (rec.asset_id, norm_type, reading.sensor_id)
                threshold = self.config.flatline_thresholds.get(
                    norm_type,
                    DEFAULT_FLATLINE_THRESHOLDS.get(
                        norm_type,
                        FlatlineThreshold(min_consecutive_readings=5, abs_tol=1e-4),
                    ),
                )

                history = flatline_history[hist_key]
                if not history:
                    history.append(reading.raw_value)
                else:
                    last_val = history[-1]
                    if threshold.is_close(reading.raw_value, last_val):
                        history.append(reading.raw_value)
                        if len(history) >= threshold.min_consecutive_readings:
                            record_key = (rec.asset_id, norm_type, reading.timestamp, reading.sensor_id)
                            flatline_flagged_keys.add(record_key)
                            # Log diagnostic signal (strictly NOT sensor failure or asset abnormality)
                            issues.append(
                                ProcessingIssue(
                                    stage="validation",
                                    severity=IssueSeverity.WARNING,
                                    code="WARN_FLATLINE_DETECTED",
                                    message=(
                                        f"Data-quality diagnostic: Channel {norm_type.value} has remained identical "
                                        f"for {len(history)} consecutive intervals (value={reading.raw_value}, abs_tol={threshold.abs_tol}). "
                                        f"Requires data-quality review; does not assert sensor failure or asset abnormality."
                                    ),
                                    field_name=norm_type.value,
                                )
                            )
                    else:
                        # Reset history on value change
                        flatline_history[hist_key] = [reading.raw_value]

        # 5. Process Each Record & Validate Channels
        validated_records: List[ValidatedTelemetryRecord] = []
        valid_count = 0
        suspect_count = 0
        bad_count = 0
        missing_count = 0
        dropped_count = 0

        for rec in sorted_records:
            record_validated, rec_issues, rec_status = self._validate_single_record(
                rec=rec,
                conflicting_keys=conflicting_keys,
                flatline_keys=flatline_flagged_keys,
            )
            issues.extend(rec_issues)

            if record_validated is not None:
                validated_records.append(record_validated)
                if rec_status == MeasurementQuality.GOOD:
                    valid_count += 1
                elif rec_status == MeasurementQuality.SUSPECT:
                    suspect_count += 1
                elif rec_status == MeasurementQuality.BAD:
                    bad_count += 1
                elif rec_status == MeasurementQuality.MISSING:
                    missing_count += 1
            else:
                dropped_count += 1

        summary = ValidationSummary(
            total_records=len(batch.records),
            valid_records=valid_count,
            suspect_records=suspect_count,
            bad_records=bad_count,
            missing_records=missing_count,
            dropped_records=dropped_count,
        )

        val_batch = ValidatedTelemetryBatch(
            asset_id=batch.asset_id,
            nominal_interval_seconds=batch.nominal_interval_seconds,
            records=validated_records,
            validation_summary=summary,
            is_monotonically_ordered=is_monotonically_ordered,
        )

        return val_batch, issues

    def _validate_single_record(
        self,
        rec: RawTelemetryRecord,
        conflicting_keys: Set[Tuple[str, MeasurementType, datetime, Optional[str]]],
        flatline_keys: Set[Tuple[str, MeasurementType, datetime, Optional[str]]],
    ) -> Tuple[Optional[ValidatedTelemetryRecord], List[ProcessingIssue], MeasurementQuality]:
        """Validates a single telemetry record across all channels."""
        record_issues: List[ProcessingIssue] = []
        channel_measurements: Dict[MeasurementType, Measurement[float]] = {}
        worst_quality = MeasurementQuality.GOOD

        # Index readings by resolved MeasurementType (latest reading wins if identical duplicate)
        readings_map: Dict[MeasurementType, RawTelemetryReading] = {}
        for r in rec.readings:
            mtype = self._resolve_channel_type(r.channel_tag)
            if mtype is None:
                record_issues.append(
                    ProcessingIssue(
                        stage="validation",
                        severity=IssueSeverity.WARNING,
                        code="WARN_UNSUPPORTED_CHANNEL",
                        message=f"Ignoring unsupported channel tag '{r.channel_tag}'.",
                        field_name=r.channel_tag,
                    )
                )
                continue
            readings_map[mtype] = r

        # Validate each primary channel
        all_channels = [
            MeasurementType.VOLTAGE_A,
            MeasurementType.VOLTAGE_B,
            MeasurementType.VOLTAGE_C,
            MeasurementType.CURRENT_A,
            MeasurementType.CURRENT_B,
            MeasurementType.CURRENT_C,
            MeasurementType.FREQUENCY,
            MeasurementType.AMBIENT_TEMPERATURE,
            MeasurementType.ACTIVE_POWER,
            MeasurementType.REACTIVE_POWER,
            MeasurementType.POWER_FACTOR,
        ]

        for mtype in all_channels:
            reading = readings_map.get(mtype)
            measurement, m_issues = self._validate_channel_reading(
                mtype=mtype,
                reading=reading,
                asset_id=rec.asset_id,
                rec_ts=rec.timestamp,
                conflicting_keys=conflicting_keys,
                flatline_keys=flatline_keys,
            )
            record_issues.extend(m_issues)
            channel_measurements[mtype] = measurement

            # Track worst quality in record
            if measurement.quality == MeasurementQuality.BAD and worst_quality != MeasurementQuality.BAD:
                worst_quality = MeasurementQuality.BAD
            elif measurement.quality == MeasurementQuality.SUSPECT and worst_quality == MeasurementQuality.GOOD:
                worst_quality = MeasurementQuality.SUSPECT

        if self.config.strict_mode:
            bad_issues = [i for i in record_issues if i.severity == IssueSeverity.CRITICAL]
            if bad_issues:
                raise TelemetryValidationError(f"Strict validation failed: {bad_issues[0].message}")

        # Construct ValidatedTelemetryRecord
        val_rec = ValidatedTelemetryRecord(
            asset_id=rec.asset_id,
            timestamp=rec.timestamp,
            voltage_a=channel_measurements[MeasurementType.VOLTAGE_A],
            voltage_b=channel_measurements[MeasurementType.VOLTAGE_B],
            voltage_c=channel_measurements[MeasurementType.VOLTAGE_C],
            current_a=channel_measurements[MeasurementType.CURRENT_A],
            current_b=channel_measurements[MeasurementType.CURRENT_B],
            current_c=channel_measurements[MeasurementType.CURRENT_C],
            frequency=channel_measurements[MeasurementType.FREQUENCY],
            ambient_temp=channel_measurements.get(MeasurementType.AMBIENT_TEMPERATURE),
            active_power_kw=channel_measurements.get(MeasurementType.ACTIVE_POWER),
            reactive_power_kvar=channel_measurements.get(MeasurementType.REACTIVE_POWER),
            power_factor=channel_measurements.get(MeasurementType.POWER_FACTOR),
        )

        return val_rec, record_issues, worst_quality

    def _validate_channel_reading(
        self,
        mtype: MeasurementType,
        reading: Optional[RawTelemetryReading],
        asset_id: str,
        rec_ts: datetime,
        conflicting_keys: Set[Tuple[str, MeasurementType, datetime, Optional[str]]],
        flatline_keys: Set[Tuple[str, MeasurementType, datetime, Optional[str]]],
    ) -> Tuple[Measurement[float], List[ProcessingIssue]]:
        """
        Validates a single channel measurement against schema, units,
        generic sanity conventions, asset operating limits, duplicates, and flatline.
        """
        issues: List[ProcessingIssue] = []
        default_unit = self._default_unit_for(mtype)

        # 1. Missing Data Handling
        if reading is None or reading.raw_value is None:
            return (
                Measurement.create_missing(
                    unit=default_unit,
                    timestamp=rec_ts,
                    reason=f"Channel {mtype.value} unmetered or null in raw record",
                ),
                issues,
            )

        val = reading.raw_value
        unit = reading.source_unit or default_unit
        sensor_id = reading.sensor_id
        quality = MeasurementQuality.GOOD
        evidence = EvidenceClassification.MEASURED

        # 2. Check Numeric Validity
        if math.isnan(val) or math.isinf(val):
            issue = ProcessingIssue(
                stage="validation",
                severity=IssueSeverity.CRITICAL,
                code="ERR_INVALID_NUMERIC",
                message=f"Channel {mtype.value} has non-finite numeric value {val}.",
                field_name=mtype.value,
            )
            issues.append(issue)
            if self.config.strict_mode:
                raise TelemetryValidationError(issue.message)
            return (
                Measurement(
                    value=None,
                    unit=unit,
                    evidence=EvidenceClassification.UNKNOWN,
                    quality=MeasurementQuality.BAD,
                    timestamp=rec_ts,
                    sensor_id=sensor_id,
                ),
                issues,
            )

        # 3. Unit Validation
        allowed_units = ALLOWED_UNITS_BY_TYPE.get(mtype, set())
        if unit not in allowed_units:
            issue = ProcessingIssue(
                stage="validation",
                severity=IssueSeverity.CRITICAL,
                code="ERR_UNSUPPORTED_UNIT",
                message=(
                    f"Unit '{unit}' is not an allowed engineering unit for {mtype.value}. "
                    f"Expected one of: {sorted(list(allowed_units))}."
                ),
                field_name=mtype.value,
            )
            issues.append(issue)
            if self.config.strict_mode:
                raise TelemetryValidationError(issue.message)
            quality = MeasurementQuality.BAD

        # 4. Range Validation against Configurable Generic Sanity Conventions
        sanity_limit = self.config.sanity_limits.get(mtype)
        if sanity_limit is not None:
            if val < sanity_limit.min_value or val > sanity_limit.max_value:
                issue = ProcessingIssue(
                    stage="validation",
                    severity=IssueSeverity.CRITICAL,
                    code="ERR_SANITY_LIMIT_EXCEEDED",
                    message=(
                        f"Value {val} {unit} for {mtype.value} violates GridPulse data-quality sanity convention "
                        f"[{sanity_limit.min_value}, {sanity_limit.max_value}]. Rationale: {sanity_limit.rationale}"
                    ),
                    field_name=mtype.value,
                )
                issues.append(issue)
                if self.config.strict_mode:
                    raise PhysicalBoundaryError(issue.message)
                if sanity_limit.min_value >= 0 and val < sanity_limit.min_value:
                    # Physically impossible negative value for a non-negative quantity
                    quality = MeasurementQuality.BAD
                else:
                    # Exceeding upper scale boundaries
                    quality = MeasurementQuality.OUT_OF_RANGE

        # 5. Power Factor Specific Domain Validation
        if mtype == MeasurementType.POWER_FACTOR:
            # IEEE convention: range [-1.0, 1.0]
            if abs(val) > 1.0:
                issue = ProcessingIssue(
                    stage="validation",
                    severity=IssueSeverity.CRITICAL,
                    code="ERR_POWER_FACTOR_OUT_OF_BOUNDS",
                    message=(
                        f"Power factor value {val} violates standard mathematical range [-1.0, 1.0]. "
                        f"Step 2 validates externally supplied power factor; actual calculations are deferred."
                    ),
                    field_name=mtype.value,
                )
                issues.append(issue)
                if self.config.strict_mode:
                    raise PhysicalBoundaryError(issue.message)
                quality = MeasurementQuality.BAD

        # 6. Asset-Specific Operating Limits (Kept Separate from Data Quality!)
        if self.asset_spec and quality == MeasurementQuality.GOOD:
            op_issues = self._check_asset_operating_limits(mtype, val, unit)
            issues.extend(op_issues)
            # CRITICAL RULE: Preserving quality as GOOD! Exceeding operating limit is an
            # operational finding, NOT a data-quality failure.

        # 7. Check Conflicting Duplicates
        duplicate_key = (asset_id, mtype, rec_ts, sensor_id)
        if duplicate_key in conflicting_keys:
            quality = MeasurementQuality.SUSPECT

        # 8. Check Flatline Condition
        if duplicate_key in flatline_keys and quality == MeasurementQuality.GOOD:
            quality = MeasurementQuality.SUSPECT

        measurement = Measurement(
            value=val if quality != MeasurementQuality.BAD else None,
            unit=unit,
            evidence=evidence if quality != MeasurementQuality.BAD else EvidenceClassification.UNKNOWN,
            quality=quality,
            timestamp=rec_ts,
            sensor_id=sensor_id,
        )

        return measurement, issues

    def _check_asset_operating_limits(
        self,
        mtype: MeasurementType,
        val: float,
        unit: str,
    ) -> List[ProcessingIssue]:
        """
        Evaluates physical value against asset nameplate operational limits.
        Preserves data quality as GOOD while recording operational findings.
        """
        op_issues: List[ProcessingIssue] = []
        if not self.asset_spec:
            return op_issues

        limits = self.asset_spec.operational_limits

        # Check Voltage Tolerances against secondary nominal voltage
        if mtype in (
            MeasurementType.VOLTAGE_A,
            MeasurementType.VOLTAGE_B,
            MeasurementType.VOLTAGE_C,
            MeasurementType.VOLTAGE_AVG,
        ):
            # Convert to V if in kV
            v_val = val * 1000.0 if unit == "kV" else val
            nom_v = self.asset_spec.secondary_voltage_v
            # Phase-to-neutral nominal voltage for 3-phase wye systems (nom_v / sqrt(3))
            v_base = nom_v / math.sqrt(3) if self.asset_spec.phases == 3 and v_val < nom_v * 0.8 else nom_v

            min_v = v_base * limits.voltage_tolerance_lower_pu
            max_v = v_base * limits.voltage_tolerance_upper_pu

            if v_val < min_v or v_val > max_v:
                op_issues.append(
                    ProcessingIssue(
                        stage="validation",
                        severity=IssueSeverity.WARNING,
                        code="OPERATIONAL_LIMIT_VOLTAGE_EXCURSION",
                        message=(
                            f"Voltage {v_val:.1f} V on {mtype.value} exceeds configured asset operational envelope "
                            f"[{min_v:.1f} V, {max_v:.1f} V] ({limits.voltage_tolerance_lower_pu:.2f}-{limits.voltage_tolerance_upper_pu:.2f} pu). "
                            f"Preserved as valid measurement for downstream analysis."
                        ),
                        field_name=mtype.value,
                    )
                )

        return op_issues

    def _resolve_channel_type(self, tag: str) -> Optional[MeasurementType]:
        """Resolves raw channel string into canonical MeasurementType enum."""
        clean_tag = tag.strip().lower()
        if clean_tag in CHANNEL_TAG_ALIASES:
            return CHANNEL_TAG_ALIASES[clean_tag]
        # Direct enum name match
        try:
            return MeasurementType(tag.upper())
        except ValueError:
            return None

    def _default_unit_for(self, mtype: MeasurementType) -> str:
        """Returns the canonical baseline unit for a measurement type."""
        defaults = {
            MeasurementType.VOLTAGE_A: "V",
            MeasurementType.VOLTAGE_B: "V",
            MeasurementType.VOLTAGE_C: "V",
            MeasurementType.VOLTAGE_AVG: "V",
            MeasurementType.CURRENT_A: "A",
            MeasurementType.CURRENT_B: "A",
            MeasurementType.CURRENT_C: "A",
            MeasurementType.CURRENT_AVG: "A",
            MeasurementType.ACTIVE_POWER: "kW",
            MeasurementType.REACTIVE_POWER: "kVAR",
            MeasurementType.APPARENT_POWER: "kVA",
            MeasurementType.POWER_FACTOR: "ratio",
            MeasurementType.FREQUENCY: "Hz",
            MeasurementType.AMBIENT_TEMPERATURE: "degC",
        }
        return defaults.get(mtype, "")

    def _empty_batch(
        self,
        asset_id: str,
        issues: List[ProcessingIssue],
    ) -> Tuple[ValidatedTelemetryBatch, List[ProcessingIssue]]:
        """Constructs an empty validated batch in failure scenarios."""
        summary = ValidationSummary(
            total_records=0,
            valid_records=0,
            suspect_records=0,
            bad_records=0,
            missing_records=0,
            dropped_records=0,
        )
        return (
            ValidatedTelemetryBatch(
                asset_id=asset_id,
                nominal_interval_seconds=60,
                records=[],
                validation_summary=summary,
                is_monotonically_ordered=True,
            ),
            issues,
        )
