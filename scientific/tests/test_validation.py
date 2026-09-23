"""
GridPulse — Phase 2 Step 2 Data Validation & Ingestion Unit Tests
Tests all 20 required behaviors and the five approved corrections.
"""

from datetime import datetime, timezone
import math
import unittest

from scientific.contracts.asset import (
    CoolingType,
    InsulationClass,
    OperationalLimits,
    TransformerAssetSpec,
    WindingMaterial,
)
from scientific.contracts.enums import (
    EvidenceClassification,
    IssueSeverity,
    MeasurementQuality,
)
from scientific.contracts.issues import (
    PhysicalBoundaryError,
    ProcessingIssue,
    TelemetryValidationError,
)
from scientific.ingestion.contracts import (
    RawTelemetryBatch,
    RawTelemetryReading,
    RawTelemetryRecord,
)
from scientific.ingestion.parser import parse_raw_telemetry_batch
from scientific.validation.engine import TelemetryValidator
from scientific.validation.rules import (
    FlatlineThreshold,
    GenericSanityLimits,
    MeasurementType,
    ValidationConfig,
)


class TestDataValidationRules(unittest.TestCase):
    """Test suite covering the full Step 2 Data Validation pipeline."""

    def setUp(self):
        self.asset_id = "TX-SUB01-DT04"
        self.asset_spec = TransformerAssetSpec(
            asset_id=self.asset_id,
            rated_power_kva=500.0,
            primary_voltage_v=11000.0,
            secondary_voltage_v=433.0,
            rated_frequency_hz=50.0,
            phases=3,
            cooling_type=CoolingType.ONAN,
            winding_material=WindingMaterial.COPPER,
            insulation_class=InsulationClass.CLASS_A_105,
            operational_limits=OperationalLimits(
                voltage_tolerance_lower_pu=0.90,
                voltage_tolerance_upper_pu=1.10,
            ),
        )
        self.validator = TelemetryValidator(asset_spec=self.asset_spec)
        self.strict_validator = TelemetryValidator(
            config=ValidationConfig(strict_mode=True),
            asset_spec=self.asset_spec,
        )

    def _make_sample_record(
        self,
        ts: datetime,
        v_a: float = 240.0,
        v_b: float = 240.0,
        v_c: float = 240.0,
        i_a: float = 50.0,
        i_b: float = 50.0,
        i_c: float = 50.0,
        freq: float = 50.0,
        pf: float = 0.95,
        t_amb: float = 25.0,
    ) -> RawTelemetryRecord:
        """Helper to create a standard valid three-phase raw record."""
        return RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[
                RawTelemetryReading(channel_tag="voltage_a", raw_value=v_a, source_unit="V", timestamp=ts),
                RawTelemetryReading(channel_tag="voltage_b", raw_value=v_b, source_unit="V", timestamp=ts),
                RawTelemetryReading(channel_tag="voltage_c", raw_value=v_c, source_unit="V", timestamp=ts),
                RawTelemetryReading(channel_tag="current_a", raw_value=i_a, source_unit="A", timestamp=ts),
                RawTelemetryReading(channel_tag="current_b", raw_value=i_b, source_unit="A", timestamp=ts),
                RawTelemetryReading(channel_tag="current_c", raw_value=i_c, source_unit="A", timestamp=ts),
                RawTelemetryReading(channel_tag="frequency", raw_value=freq, source_unit="Hz", timestamp=ts),
                RawTelemetryReading(channel_tag="power_factor", raw_value=pf, source_unit="ratio", timestamp=ts),
                RawTelemetryReading(channel_tag="ambient_temp", raw_value=t_amb, source_unit="degC", timestamp=ts),
            ],
        )

    # -------------------------------------------------------------------------
    # Test 1: Valid Telemetry Accepted
    # -------------------------------------------------------------------------
    def test_01_valid_telemetry_accepted(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        record = self._make_sample_record(ts)
        batch = RawTelemetryBatch(
            asset_id=self.asset_id,
            nominal_interval_seconds=60,
            records=[record],
        )
        val_batch, issues = self.validator.validate_batch(batch)

        self.assertEqual(val_batch.validation_summary.valid_records, 1)
        self.assertEqual(val_batch.validation_summary.bad_records, 0)
        self.assertEqual(len(val_batch.records), 1)
        rec = val_batch.records[0]
        self.assertEqual(rec.voltage_a.quality, MeasurementQuality.GOOD)
        self.assertEqual(rec.voltage_a.evidence, EvidenceClassification.MEASURED)
        self.assertEqual(rec.voltage_a.value, 240.0)
        self.assertEqual(rec.frequency.quality, MeasurementQuality.GOOD)
        self.assertEqual(rec.frequency.value, 50.0)

    # -------------------------------------------------------------------------
    # Test 2: Missing Asset ID Rejected
    # -------------------------------------------------------------------------
    def test_02_missing_asset_id_rejected(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        # In parser
        with self.assertRaises(TelemetryValidationError) as ctx:
            parse_raw_telemetry_batch({"nominal_interval_seconds": 60, "records": []}, strict=True)
        self.assertIn("asset_id", str(ctx.exception))

        # In validator strict mode
        with self.assertRaises(ValueError):
            RawTelemetryBatch(asset_id="", nominal_interval_seconds=60, records=[])

    # -------------------------------------------------------------------------
    # Test 3: Missing Measurement Identifier Handled
    # -------------------------------------------------------------------------
    def test_03_missing_measurement_identifier(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        # Empty channel tag rejected in reading post_init
        with self.assertRaises(ValueError):
            RawTelemetryReading(channel_tag="", raw_value=230.0, source_unit="V", timestamp=ts)

        # In parser with missing channel_tag in strict mode
        payload = {
            "asset_id": self.asset_id,
            "records": [{"timestamp": ts.isoformat(), "readings": [{"raw_value": 230.0, "source_unit": "V"}]}],
        }
        with self.assertRaises(TelemetryValidationError):
            parse_raw_telemetry_batch(payload, strict=True)

    # -------------------------------------------------------------------------
    # Test 4: Missing Timestamp Rejected
    # -------------------------------------------------------------------------
    def test_04_missing_timestamp_rejected(self):
        payload = {
            "asset_id": self.asset_id,
            "records": [{"readings": [{"channel_tag": "va", "raw_value": 230.0, "source_unit": "V"}]}],
        }
        with self.assertRaises(TelemetryValidationError) as ctx:
            parse_raw_telemetry_batch(payload, strict=True)
        self.assertIn("timestamp", str(ctx.exception))

    # -------------------------------------------------------------------------
    # Test 5: Timezone-Naive Timestamp Rejected
    # -------------------------------------------------------------------------
    def test_05_timezone_naive_timestamp_rejected(self):
        naive_str = "2026-09-23T12:00:00"  # No UTC offset or Z
        payload = {
            "asset_id": self.asset_id,
            "records": [{"timestamp": naive_str, "readings": [{"channel_tag": "va", "raw_value": 230.0, "source_unit": "V"}]}],
        }
        with self.assertRaises(TelemetryValidationError) as ctx:
            parse_raw_telemetry_batch(payload, strict=True)
        self.assertIn("timezone-naive", str(ctx.exception))

    # -------------------------------------------------------------------------
    # Test 6: Malformed Timestamp Rejected
    # -------------------------------------------------------------------------
    def test_06_malformed_timestamp_rejected(self):
        payload = {
            "asset_id": self.asset_id,
            "records": [{"timestamp": "not-a-timestamp", "readings": []}],
        }
        with self.assertRaises(TelemetryValidationError):
            parse_raw_telemetry_batch(payload, strict=True)

    # -------------------------------------------------------------------------
    # Test 7: Unsupported Unit Rejected
    # -------------------------------------------------------------------------
    def test_07_unsupported_unit_rejected(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        record = RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[RawTelemetryReading(channel_tag="voltage_a", raw_value=230.0, source_unit="psi", timestamp=ts)],
        )
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[record])

        # In strict mode: raises exception
        with self.assertRaises(TelemetryValidationError) as ctx:
            self.strict_validator.validate_batch(batch)
        self.assertIn("allowed engineering unit", str(ctx.exception))

        # In fault-tolerant mode: flagged as BAD quality
        val_batch, issues = self.validator.validate_batch(batch)
        self.assertEqual(val_batch.records[0].voltage_a.quality, MeasurementQuality.BAD)
        self.assertTrue(any(i.code == "ERR_UNSUPPORTED_UNIT" for i in issues))

    # -------------------------------------------------------------------------
    # Test 8: Invalid Numeric Value Detected
    # -------------------------------------------------------------------------
    def test_08_invalid_numeric_value_detected(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        record = RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[RawTelemetryReading(channel_tag="voltage_a", raw_value=float("nan"), source_unit="V", timestamp=ts)],
        )
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[record])

        val_batch, issues = self.validator.validate_batch(batch)
        self.assertEqual(val_batch.records[0].voltage_a.quality, MeasurementQuality.BAD)
        self.assertIsNone(val_batch.records[0].voltage_a.value)
        self.assertTrue(any(i.code == "ERR_INVALID_NUMERIC" for i in issues))

    # -------------------------------------------------------------------------
    # Test 9: Missing Telemetry Represented Correctly
    # -------------------------------------------------------------------------
    def test_09_missing_telemetry_representation(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        # Omit current_b completely from record
        record = RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[
                RawTelemetryReading(channel_tag="voltage_a", raw_value=240.0, source_unit="V", timestamp=ts),
                RawTelemetryReading(channel_tag="current_a", raw_value=50.0, source_unit="A", timestamp=ts),
                RawTelemetryReading(channel_tag="current_b", raw_value=None, source_unit="A", timestamp=ts),  # Explicit None
            ],
        )
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[record])
        val_batch, _ = self.validator.validate_batch(batch)

        rec = val_batch.records[0]
        # Missing current_b must be None, MISSING, UNKNOWN
        self.assertIsNone(rec.current_b.value)
        self.assertEqual(rec.current_b.quality, MeasurementQuality.MISSING)
        self.assertEqual(rec.current_b.evidence, EvidenceClassification.UNKNOWN)

        # Omitted voltage_c must also be None, MISSING, UNKNOWN
        self.assertIsNone(rec.voltage_c.value)
        self.assertEqual(rec.voltage_c.quality, MeasurementQuality.MISSING)
        self.assertEqual(rec.voltage_c.evidence, EvidenceClassification.UNKNOWN)

    # -------------------------------------------------------------------------
    # Test 10: Duplicate Identical Record Detected & Provenance Preserved
    # -------------------------------------------------------------------------
    def test_10_duplicate_identical_record_detected(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        record = RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[
                RawTelemetryReading(channel_tag="voltage_a", raw_value=240.0, source_unit="V", timestamp=ts),
                RawTelemetryReading(channel_tag="voltage_a", raw_value=240.0, source_unit="V", timestamp=ts),  # Duplicate identical
            ],
        )
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[record])
        val_batch, issues = self.validator.validate_batch(batch)

        rec = val_batch.records[0]
        self.assertEqual(rec.voltage_a.value, 240.0)
        self.assertEqual(rec.voltage_a.quality, MeasurementQuality.GOOD)
        # Provenance trace must be recorded
        self.assertTrue(any(i.code == "INFO_DUPLICATE_IDENTICAL" for i in issues))

    # -------------------------------------------------------------------------
    # Test 11: Conflicting Duplicate Detected and Flagged SUSPECT
    # -------------------------------------------------------------------------
    def test_11_duplicate_conflicting_detected(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        record = RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[
                RawTelemetryReading(channel_tag="voltage_a", raw_value=240.0, source_unit="V", timestamp=ts),
                RawTelemetryReading(channel_tag="voltage_a", raw_value=210.0, source_unit="V", timestamp=ts),  # Conflicting!
            ],
        )
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[record])
        val_batch, issues = self.validator.validate_batch(batch)

        rec = val_batch.records[0]
        # Conflicting duplicate must NOT silently become clean telemetry
        self.assertEqual(rec.voltage_a.quality, MeasurementQuality.SUSPECT)
        self.assertTrue(any(i.code == "WARN_DUPLICATE_CONFLICTING" for i in issues))

    # -------------------------------------------------------------------------
    # Test 12: Flatline Detection Works Deterministically Across Sequence
    # -------------------------------------------------------------------------
    def test_12_flatline_detection_deterministic(self):
        records = []
        for i in range(6):  # 6 consecutive intervals (>= 5 threshold)
            ts = datetime(2026, 9, 23, 12, i, 0, tzinfo=timezone.utc)
            # voltage_a remains identical at 235.0 V
            records.append(
                RawTelemetryRecord(
                    asset_id=self.asset_id,
                    timestamp=ts,
                    readings=[
                        RawTelemetryReading(channel_tag="voltage_a", raw_value=235.0, source_unit="V", timestamp=ts),
                        RawTelemetryReading(channel_tag="voltage_b", raw_value=230.0 + i * 0.5, source_unit="V", timestamp=ts),  # Varying
                    ],
                )
            )
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=records)
        val_batch, issues = self.validator.validate_batch(batch)

        # 5th and 6th records should be flagged as SUSPECT for voltage_a
        self.assertEqual(val_batch.records[0].voltage_a.quality, MeasurementQuality.GOOD)
        self.assertEqual(val_batch.records[4].voltage_a.quality, MeasurementQuality.SUSPECT)
        self.assertEqual(val_batch.records[5].voltage_a.quality, MeasurementQuality.SUSPECT)

        # voltage_b varied and must remain GOOD
        self.assertEqual(val_batch.records[5].voltage_b.quality, MeasurementQuality.GOOD)
        self.assertTrue(any(i.code == "WARN_FLATLINE_DETECTED" for i in issues))

    # -------------------------------------------------------------------------
    # Test 13: Flatline Does NOT Claim Sensor Failure or Asset Abnormality
    # -------------------------------------------------------------------------
    def test_13_flatline_does_not_claim_sensor_failure(self):
        records = [
            RawTelemetryRecord(
                asset_id=self.asset_id,
                timestamp=datetime(2026, 9, 23, 12, i, 0, tzinfo=timezone.utc),
                readings=[RawTelemetryReading(channel_tag="frequency", raw_value=50.000, source_unit="Hz", timestamp=datetime(2026, 9, 23, 12, i, 0, tzinfo=timezone.utc))],
            )
            for i in range(6)
        ]
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=records)
        _, issues = self.validator.validate_batch(batch)

        flatline_issues = [i for i in issues if i.code == "WARN_FLATLINE_DETECTED"]
        self.assertTrue(len(flatline_issues) > 0)
        for issue in flatline_issues:
            self.assertIn("does not assert sensor failure or asset abnormality", issue.message)
            self.assertNotIn("sensor failure", issue.message.lower().replace("does not assert sensor failure", ""))
            self.assertNotIn("sensor malfunction", issue.message.lower())

    # -------------------------------------------------------------------------
    # Test 14: Range Validation Enforces Generic Sanity Conventions
    # -------------------------------------------------------------------------
    def test_14_range_validation_sanity_limits(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        # Negative frequency and extreme voltage
        record = RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[
                RawTelemetryReading(channel_tag="frequency", raw_value=-10.0, source_unit="Hz", timestamp=ts),
                RawTelemetryReading(channel_tag="voltage_a", raw_value=250000.0, source_unit="V", timestamp=ts),  # > 100 kV sanity
            ],
        )
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[record])

        val_batch, issues = self.validator.validate_batch(batch)
        self.assertIn(val_batch.records[0].frequency.quality, (MeasurementQuality.OUT_OF_RANGE, MeasurementQuality.BAD))
        self.assertEqual(val_batch.records[0].voltage_a.quality, MeasurementQuality.OUT_OF_RANGE)
        self.assertTrue(any(i.code == "ERR_SANITY_LIMIT_EXCEEDED" for i in issues))

    # -------------------------------------------------------------------------
    # Test 15: Asset-Specific Limits Distinguishable from Generic Sanity Limits
    # -------------------------------------------------------------------------
    def test_15_asset_specific_limits_distinguishable(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        # Nominal line-to-neutral is 433 / sqrt(3) ~= 250 V.
        # Upper limit is 250 * 1.10 = 275 V.
        # 300 V is physically plausible (< 100 kV generic sanity), but exceeds asset operating limit.
        record = RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[RawTelemetryReading(channel_tag="voltage_a", raw_value=300.0, source_unit="V", timestamp=ts)],
        )
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[record])
        val_batch, issues = self.validator.validate_batch(batch)

        rec = val_batch.records[0]
        # Telemetry quality must remain GOOD because the measurement is physically plausible!
        self.assertEqual(rec.voltage_a.quality, MeasurementQuality.GOOD)
        self.assertEqual(rec.voltage_a.value, 300.0)

        # Operational finding must be separately logged without marking telemetry BAD
        op_issues = [i for i in issues if i.code == "OPERATIONAL_LIMIT_VOLTAGE_EXCURSION"]
        self.assertEqual(len(op_issues), 1)
        self.assertEqual(op_issues[0].severity, IssueSeverity.WARNING)
        self.assertIn("exceeds configured asset operational envelope", op_issues[0].message)

    # -------------------------------------------------------------------------
    # Test 16: Invalid Records Cannot Silently Become Valid Records
    # -------------------------------------------------------------------------
    def test_16_invalid_records_cannot_silently_become_valid(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        record = RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[RawTelemetryReading(channel_tag="voltage_a", raw_value=-50.0, source_unit="V", timestamp=ts)],
        )
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[record])
        val_batch, _ = self.validator.validate_batch(batch)

        # Cannot silently be GOOD or 0.0
        self.assertNotEqual(val_batch.records[0].voltage_a.quality, MeasurementQuality.GOOD)
        self.assertIsNone(val_batch.records[0].voltage_a.value)

    # -------------------------------------------------------------------------
    # Test 17: Fault-Tolerant Mode Isolates Invalid Records Without Crashing
    # -------------------------------------------------------------------------
    def test_17_fault_tolerant_mode_isolates_without_crashing(self):
        ts1 = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 9, 23, 12, 1, 0, tzinfo=timezone.utc)
        records = [
            RawTelemetryRecord(
                asset_id=self.asset_id,
                timestamp=ts1,
                readings=[RawTelemetryReading(channel_tag="voltage_a", raw_value=240.0, source_unit="V", timestamp=ts1)],
            ),
            RawTelemetryRecord(
                asset_id=self.asset_id,
                timestamp=ts2,
                readings=[RawTelemetryReading(channel_tag="voltage_a", raw_value=-999.0, source_unit="V", timestamp=ts2)],  # Bad
            ),
        ]
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=records)

        # Fault-tolerant mode (default) must not raise an exception
        val_batch, issues = self.validator.validate_batch(batch)
        self.assertEqual(len(val_batch.records), 2)
        self.assertEqual(val_batch.records[0].voltage_a.quality, MeasurementQuality.GOOD)
        self.assertEqual(val_batch.records[1].voltage_a.quality, MeasurementQuality.BAD)

    # -------------------------------------------------------------------------
    # Test 18: Strict Mode Follows Defined Contract (Raises Exceptions)
    # -------------------------------------------------------------------------
    def test_18_strict_mode_raises_exceptions(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        record = RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[RawTelemetryReading(channel_tag="frequency", raw_value=-5.0, source_unit="Hz", timestamp=ts)],
        )
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[record])

        with self.assertRaises(PhysicalBoundaryError):
            self.strict_validator.validate_batch(batch)

    # -------------------------------------------------------------------------
    # Test 19: ProcessingIssue Records Contain Useful Diagnostics
    # -------------------------------------------------------------------------
    def test_19_processing_issue_diagnostics(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        record = RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[RawTelemetryReading(channel_tag="voltage_a", raw_value=250000.0, source_unit="V", timestamp=ts)],
        )
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[record])
        _, issues = self.validator.validate_batch(batch)

        issue = issues[0]
        self.assertEqual(issue.stage, "validation")
        self.assertEqual(issue.code, "ERR_SANITY_LIMIT_EXCEEDED")
        self.assertEqual(issue.severity, IssueSeverity.CRITICAL)
        self.assertIsNotNone(issue.timestamp)
        self.assertEqual(issue.field_name, "VOLTAGE_A")
        self.assertIn("GridPulse data-quality sanity convention", issue.message)

    # -------------------------------------------------------------------------
    # Test 20: Validated Telemetry Serialization is Deterministic
    # -------------------------------------------------------------------------
    def test_20_serialization_deterministic(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        record = self._make_sample_record(ts)
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[record])
        val_batch, _ = self.validator.validate_batch(batch)

        rec = val_batch.records[0]
        # Verify attributes exist and serialize cleanly
        self.assertEqual(rec.asset_id, self.asset_id)
        self.assertEqual(rec.timestamp.isoformat(), "2026-09-23T12:00:00+00:00")
        self.assertEqual(rec.voltage_a.quality.value, "GOOD")
        self.assertEqual(rec.voltage_a.evidence.value, "MEASURED")

    # -------------------------------------------------------------------------
    # Test 21: Power Factor Validation Domain [-1.0, 1.0] (Correction #2)
    # -------------------------------------------------------------------------
    def test_21_power_factor_validation_domain(self):
        ts = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)

        # Valid power factor: 0.95
        rec_valid = RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[RawTelemetryReading(channel_tag="power_factor", raw_value=0.95, source_unit="ratio", timestamp=ts)],
        )
        batch_valid = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[rec_valid])
        val_valid, _ = self.validator.validate_batch(batch_valid)
        self.assertEqual(val_valid.records[0].power_factor.quality, MeasurementQuality.GOOD)
        self.assertEqual(val_valid.records[0].power_factor.value, 0.95)

        # Negative power factor (leading): -0.85 (valid in IEEE convention)
        rec_neg = RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[RawTelemetryReading(channel_tag="power_factor", raw_value=-0.85, source_unit="ratio", timestamp=ts)],
        )
        batch_neg = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[rec_neg])
        val_neg, _ = self.validator.validate_batch(batch_neg)
        self.assertEqual(val_neg.records[0].power_factor.quality, MeasurementQuality.GOOD)
        self.assertEqual(val_neg.records[0].power_factor.value, -0.85)

        # Invalid power factor: 1.25 (|PF| > 1.0)
        rec_inv = RawTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            readings=[RawTelemetryReading(channel_tag="power_factor", raw_value=1.25, source_unit="ratio", timestamp=ts)],
        )
        batch_inv = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=[rec_inv])
        val_inv, issues = self.validator.validate_batch(batch_inv)
        self.assertEqual(val_inv.records[0].power_factor.quality, MeasurementQuality.BAD)
        self.assertTrue(any(i.code == "ERR_POWER_FACTOR_OUT_OF_BOUNDS" for i in issues))

    # -------------------------------------------------------------------------
    # Test 22: Flatline Configurable Tolerances (Correction #3)
    # -------------------------------------------------------------------------
    def test_22_flatline_configurable_tolerances(self):
        # Configure voltage flatline threshold to abs_tol=0.5 V
        custom_config = ValidationConfig(
            flatline_thresholds={
                MeasurementType.VOLTAGE_A: FlatlineThreshold(min_consecutive_readings=3, abs_tol=0.5),
            }
        )
        custom_validator = TelemetryValidator(config=custom_config, asset_spec=self.asset_spec)

        records = [
            RawTelemetryRecord(
                asset_id=self.asset_id,
                timestamp=datetime(2026, 9, 23, 12, i, 0, tzinfo=timezone.utc),
                readings=[RawTelemetryReading(channel_tag="voltage_a", raw_value=230.0 + (i * 0.2), source_unit="V", timestamp=datetime(2026, 9, 23, 12, i, 0, tzinfo=timezone.utc))],
            )
            for i in range(4)
        ]
        # Intervals 0->1 delta=0.2 (< 0.5), 1->2 delta=0.2 (< 0.5) => 3 consecutive within abs_tol=0.5
        batch = RawTelemetryBatch(asset_id=self.asset_id, nominal_interval_seconds=60, records=records)
        val_batch, issues = custom_validator.validate_batch(batch)

        self.assertEqual(val_batch.records[2].voltage_a.quality, MeasurementQuality.SUSPECT)
        self.assertTrue(any(i.code == "WARN_FLATLINE_DETECTED" for i in issues))


if __name__ == "__main__":
    unittest.main()
