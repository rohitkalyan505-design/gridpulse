"""
GridPulse — Transformer Thermal Analysis & Insulation Degradation Engine
Part of scientific.thermal.

Phase 2 Step 5: Complete Scientific Calculation Engine (v2.5.0 Specification).
Provides:
1. Standard-specific differential thermal models: IEEE Std C57.91 vs IEC 60076-7.
2. Verified parameter provenance filtering (rejection of generic assumptions).
3. Telemetry preservation (no synthetic ambient, preservation of anomalous readings).
4. Zero speculative initial thermal states (strict quarantine on missing prior states).
5. Continuity break detection and independent post-gap sensor recovery.
6. Independent evaluation of IEEE F_AA and IEC V degradation kinetics.
7. Mandatory explicit aging standard selection for loss-of-life integration.
8. Forward-interval Riemann integration matching Phase 2 Step 4 semantics.
9. Strict evidence propagation: MEASURED -> CALCULATED vs MODELED -> MODELED.
10. Validated asset-specific reference-life normalization (elimination of universal 180k denominator).
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from scientific.contracts.enums import (
    AgingStandardPreference,
    EvidenceClassification,
    InsulationSystemType,
    IssueSeverity,
    MeasurementQuality,
    ThermalModelStandard,
)
from scientific.contracts.issues import (
    ERR_UNESTABLISHED_INITIAL_THERMAL_STATE,
    ERR_UNSPECIFIED_AGING_STANDARD,
    ERR_UNSPECIFIED_THERMAL_MODEL_STANDARD,
    ERR_UNVALIDATED_THERMAL_PARAMETERS,
    ProcessingIssue,
    WARN_ANOMALOUS_MEASURED_GRADIENT,
    WARN_INCOMPLETE_INTEGRATION_WINDOW,
    WARN_NON_MONOTONIC_TIMESTAMPS,
    WARN_TELEMETRY_GAP,
    WARN_UNCONFIGURED_REFERENCE_LIFE,
)
from scientific.contracts.measurement import CANONICAL_UNITS, Measurement
from scientific.contracts.results import (
    ThermalIntervalResult,
    ThermalStateResult,
    TransformerLoadingResult,
)
from scientific.thermal.contracts import (
    ThermalAnalysisInput,
    ThermalModelParameters,
)
from scientific.thermal.solver import (
    IEEE_REF_TEMP_NON_UPGRADED_C,
    IEEE_REF_TEMP_UPGRADED_C,
    IEC_REF_TEMP_NON_UPGRADED_C,
    IEC_REF_TEMP_UPGRADED_C,
    calculate_iec_relative_ageing_rate,
    calculate_iec_ultimate_hot_spot_rise,
    calculate_iec_ultimate_top_oil_rise,
    calculate_ieee_aging_acceleration_factor,
    calculate_ieee_ultimate_hot_spot_rise,
    calculate_ieee_ultimate_top_oil_rise,
    solve_exponential_recurrence,
)


STAGE_NAME = "thermal_analysis_engine"


class ThermalCalculationEngine:
    """
    Deterministic, production-grade engine executing transformer thermal modeling
    and insulation loss-of-life analytics.
    """

    def __init__(self, engine_version: str = "2.5.0") -> None:
        self.engine_version = engine_version

    def analyze_batch(
        self,
        input_data: ThermalAnalysisInput,
    ) -> Tuple[List[ThermalStateResult], List[ProcessingIssue]]:
        """
        Executes thermal modeling and loss-of-life integration over an ordered sequence
        of transformer loading records.
        """
        all_issues: List[ProcessingIssue] = []

        # ----------------------------------------------------------------------
        # 1. Validation of Mandatory Standards & Parameters
        # ----------------------------------------------------------------------
        model_standard = input_data.thermal_model_standard
        if model_standard is None or model_standard not in {ThermalModelStandard.IEEE, ThermalModelStandard.IEC}:
            all_issues.append(
                ProcessingIssue(
                    stage=STAGE_NAME,
                    severity=IssueSeverity.CRITICAL,
                    code=ERR_UNSPECIFIED_THERMAL_MODEL_STANDARD,
                    message=(
                        "thermal_model_standard must be explicitly specified as either "
                        "ThermalModelStandard.IEEE or ThermalModelStandard.IEC. No default fallback exists."
                    ),
                    field_name="thermal_model_standard",
                )
            )
            thermal_model_valid = False
        else:
            thermal_model_valid = True

        aging_standard = input_data.aging_standard
        if aging_standard is None or aging_standard not in {AgingStandardPreference.IEEE, AgingStandardPreference.IEC}:
            all_issues.append(
                ProcessingIssue(
                    stage=STAGE_NAME,
                    severity=IssueSeverity.CRITICAL,
                    code=ERR_UNSPECIFIED_AGING_STANDARD,
                    message=(
                        "aging_standard must be explicitly specified as either "
                        "AgingStandardPreference.IEEE or AgingStandardPreference.IEC. "
                        "No default fallback exists. Loss-of-life integration is prohibited."
                    ),
                    field_name="aging_standard",
                )
            )
            aging_standard_valid = False
        else:
            aging_standard_valid = True

        # Parameter validation
        parameters = input_data.thermal_parameters
        if parameters is None:
            all_issues.append(
                ProcessingIssue(
                    stage=STAGE_NAME,
                    severity=IssueSeverity.CRITICAL,
                    code=ERR_UNVALIDATED_THERMAL_PARAMETERS,
                    message="thermal_parameters is None. High-consequence modeled calculations require verified parameters.",
                    field_name="thermal_parameters",
                )
            )
            parameters_valid = False
        elif thermal_model_valid:
            param_issues = parameters.validate_for_high_consequence(model_standard, stage=STAGE_NAME)
            all_issues.extend(param_issues)
            has_param_errors = any(i.severity == IssueSeverity.CRITICAL for i in param_issues)
            parameters_valid = not has_param_errors
        else:
            parameters_valid = False

        # Loading records inspection
        loading_records = input_data.loading_results
        if not loading_records:
            return [], all_issues

        # ----------------------------------------------------------------------
        # 2. Extract Aligned Series & Verify Monotonic Timestamps
        # ----------------------------------------------------------------------
        n_samples = len(loading_records)
        timestamps: List[datetime] = []
        for i, lr in enumerate(loading_records):
            # Extract timestamp from loading record with strict precedence:
            # 1. lr.peak_loading_timestamp
            # 2. lr.loading_ratio_pu.timestamp (if Measurement exists and has timestamp)
            # 3. lr.calculation_provenance.get("timestamp")
            # 4. Fallback: datetime.now(timezone.utc)
            ts = lr.peak_loading_timestamp
            if ts is None and lr.loading_ratio_pu is not None and lr.loading_ratio_pu.timestamp is not None:
                ts = lr.loading_ratio_pu.timestamp
            if ts is None:
                prov_ts = lr.calculation_provenance.get("timestamp")
                if prov_ts:
                    if isinstance(prov_ts, str):
                        ts = datetime.fromisoformat(prov_ts)
                    elif isinstance(prov_ts, datetime):
                        ts = prov_ts
            if ts is None:
                ts = datetime.now(timezone.utc)
            elif ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            timestamps.append(ts)

        # Check timestamp ordering and detect duplicate / out-of-order chronology
        has_chronology_error = False
        for i in range(n_samples - 1):
            if timestamps[i + 1] <= timestamps[i]:
                has_chronology_error = True
                if timestamps[i + 1] == timestamps[i]:
                    msg = (
                        f"Duplicate timestamp encountered at index {i} and {i+1} "
                        f"({timestamps[i].isoformat()}). Forward interval duration is zero."
                    )
                else:
                    msg = (
                        f"Out-of-order timestamp at index {i+1} ({timestamps[i+1].isoformat()}) "
                        f"precedes earlier timestamp at index {i} ({timestamps[i].isoformat()}). "
                        f"Chronological sequence violated."
                    )
                all_issues.append(
                    ProcessingIssue(
                        stage=STAGE_NAME,
                        severity=IssueSeverity.WARNING,
                        code=WARN_NON_MONOTONIC_TIMESTAMPS,
                        message=msg,
                        field_name="timestamp",
                    )
                )

        amb_series = input_data.ambient_temperature_series or [None] * n_samples
        oil_series = input_data.measured_top_oil_series or [None] * n_samples
        hs_series = input_data.measured_hot_spot_series or [None] * n_samples

        tolerance_hours = input_data.continuity_tolerance_seconds / 3600.0

        # State tracking across steps
        delta_oil_prev: Optional[float] = None
        delta_hs_prev: Optional[float] = None
        has_incomplete_interval: bool = False
        step_results: List[ThermalStateResult] = []

        # ----------------------------------------------------------------------
        # 3. Main Step Execution Loop
        # ----------------------------------------------------------------------
        for k in range(n_samples):
            step_issues: List[ProcessingIssue] = []
            ts_k = timestamps[k]
            lr_k = loading_records[k]

            # Ingest ambient
            raw_amb = amb_series[k] if k < len(amb_series) else None
            if raw_amb is not None and not math.isnan(raw_amb) and not math.isinf(raw_amb):
                amb_meas = Measurement(
                    value=float(raw_amb),
                    unit="°C",
                    evidence=EvidenceClassification.MEASURED,
                    quality=MeasurementQuality.GOOD,
                    timestamp=ts_k,
                )
            else:
                amb_meas = None

            # Ingest raw sensor measurements
            raw_oil = oil_series[k] if k < len(oil_series) else None
            has_oil_sensor = raw_oil is not None and not math.isnan(raw_oil) and not math.isinf(raw_oil)

            raw_hs = hs_series[k] if k < len(hs_series) else None
            has_hs_sensor = raw_hs is not None and not math.isnan(raw_hs) and not math.isinf(raw_hs)

            # Loading ratio K_k
            if lr_k.loading_ratio_pu is not None and lr_k.loading_ratio_pu.value is not None:
                k_loading = float(lr_k.loading_ratio_pu.value)
            else:
                k_loading = 0.0

            # Forward interval geometry
            if k < n_samples - 1:
                is_chronology_break = (timestamps[k + 1] <= ts_k)
                if is_chronology_break:
                    dt_k_hours = 0.0
                    is_gap = False
                    if timestamps[k + 1] == ts_k:
                        step_issues.append(
                            ProcessingIssue(
                                stage=STAGE_NAME,
                                severity=IssueSeverity.WARNING,
                                code=WARN_NON_MONOTONIC_TIMESTAMPS,
                                message=(
                                    f"Duplicate timestamp between index {k} and {k+1} "
                                    f"({ts_k.isoformat()}). Interval cannot be integrated."
                                ),
                                field_name="timestamp",
                            )
                        )
                    else:
                        step_issues.append(
                            ProcessingIssue(
                                stage=STAGE_NAME,
                                severity=IssueSeverity.WARNING,
                                code=WARN_NON_MONOTONIC_TIMESTAMPS,
                                message=(
                                    f"Out-of-order timestamp at index {k+1} ({timestamps[k+1].isoformat()}) "
                                    f"precedes index {k} ({ts_k.isoformat()}). Interval cannot be integrated."
                                ),
                                field_name="timestamp",
                            )
                        )
                else:
                    dt_k_hours = (timestamps[k + 1] - ts_k).total_seconds() / 3600.0
                    is_gap = dt_k_hours > tolerance_hours
                    if is_gap:
                        gap_issue = ProcessingIssue(
                            stage=STAGE_NAME,
                            severity=IssueSeverity.WARNING,
                            code=WARN_TELEMETRY_GAP,
                            message=(
                                f"Telemetry interval between {ts_k.isoformat()} and {timestamps[k+1].isoformat()} "
                                f"({dt_k_hours:.3f} h) exceeded tolerance ({tolerance_hours:.3f} h). "
                                f"Severing continuous thermal state."
                            ),
                            field_name="timestamp",
                        )
                        step_issues.append(gap_issue)
                        all_issues.append(gap_issue)
            else:
                dt_k_hours = 0.0
                is_gap = False
                is_chronology_break = False

            # Check thermal state initialization at sample k
            if k == 0:
                # Initial step: check prior state
                prior = input_data.initial_prior_thermal_state
                if (
                    prior is not None
                    and prior.is_computed
                    and prior.timestamp is not None
                    and (ts_k - prior.timestamp).total_seconds() / 3600.0 <= tolerance_hours
                    and prior.asset_id == input_data.asset_id
                    and prior.top_oil_rise_k is not None
                    and prior.top_oil_rise_k.value is not None
                    and prior.hot_spot_rise_k is not None
                    and prior.hot_spot_rise_k.value is not None
                ):
                    delta_oil_prev = float(prior.top_oil_rise_k.value)
                    delta_hs_prev = float(prior.hot_spot_rise_k.value)
                else:
                    # No valid prior state!
                    delta_oil_prev = None
                    delta_hs_prev = None

                    # Direct measurements at k=0 can establish initial rise
                    if has_oil_sensor and amb_meas is not None:
                        delta_oil_prev = float(raw_oil) - amb_meas.value
                    if has_hs_sensor and has_oil_sensor:
                        delta_hs_prev = float(raw_hs) - float(raw_oil)

                    # If hot-spot cannot be initialized from sensor or prior:
                    if delta_hs_prev is None and not has_hs_sensor:
                        init_issue = ProcessingIssue(
                            stage=STAGE_NAME,
                            severity=IssueSeverity.CRITICAL,
                            code=ERR_UNESTABLISHED_INITIAL_THERMAL_STATE,
                            message=(
                                "Initial winding hot-spot thermal state cannot be established at t0 without "
                                "a valid contiguous prior state or direct winding sensor. Prohibiting assumed "
                                "zero-rise or steady-state initialization."
                            ),
                            field_name="hot_spot_temp_c",
                        )
                        step_issues.append(init_issue)
                        all_issues.append(init_issue)

            is_quarantined = (not has_hs_sensor and delta_hs_prev is None)


            # ------------------------------------------------------------------
            # 3.1 Top-Oil Temperature and Rise Resolution
            # ------------------------------------------------------------------
            top_oil_temp: Optional[Measurement[float]] = None
            top_oil_rise: Optional[Measurement[float]] = None

            if has_oil_sensor:
                top_oil_temp = Measurement(
                    value=float(raw_oil),
                    unit="°C",
                    evidence=EvidenceClassification.MEASURED,
                    quality=MeasurementQuality.GOOD,
                    timestamp=ts_k,
                )
                if amb_meas is not None:
                    rise_val = float(raw_oil) - amb_meas.value
                    top_oil_rise = Measurement(
                        value=rise_val,
                        unit="K",
                        evidence=EvidenceClassification.CALCULATED,
                        quality=MeasurementQuality.GOOD,
                        timestamp=ts_k,
                    )
                else:
                    top_oil_rise = None
            elif delta_oil_prev is not None and parameters_valid and amb_meas is not None:
                # Modeled top-oil state
                top_oil_rise = Measurement(
                    value=delta_oil_prev,
                    unit="K",
                    evidence=EvidenceClassification.MODELED,
                    quality=MeasurementQuality.GOOD,
                    timestamp=ts_k,
                )
                top_oil_temp = Measurement(
                    value=amb_meas.value + delta_oil_prev,
                    unit="°C",
                    evidence=EvidenceClassification.MODELED,
                    quality=MeasurementQuality.GOOD,
                    timestamp=ts_k,
                )
            else:
                top_oil_temp = None
                top_oil_rise = None

            # ------------------------------------------------------------------
            # 3.2 Hot-Spot Temperature and Gradient Resolution
            # ------------------------------------------------------------------
            hot_spot_temp: Optional[Measurement[float]] = None
            hot_spot_rise: Optional[Measurement[float]] = None

            if has_hs_sensor:
                hot_spot_temp = Measurement(
                    value=float(raw_hs),
                    unit="°C",
                    evidence=EvidenceClassification.MEASURED,
                    quality=MeasurementQuality.GOOD,
                    timestamp=ts_k,
                )
                if top_oil_temp is not None:
                    hs_gradient = float(raw_hs) - top_oil_temp.value
                    hot_spot_rise = Measurement(
                        value=hs_gradient,
                        unit="K",
                        evidence=EvidenceClassification.CALCULATED,
                        quality=MeasurementQuality.GOOD,
                        timestamp=ts_k,
                    )
                    # Check physical sensor inversion
                    if float(raw_hs) < top_oil_temp.value:
                        inv_issue = ProcessingIssue(
                            stage=STAGE_NAME,
                            severity=IssueSeverity.WARNING,
                            code=WARN_ANOMALOUS_MEASURED_GRADIENT,
                            message=(
                                f"Directly measured hot-spot temperature ({float(raw_hs):.2f}°C) is lower than "
                                f"top-oil temperature ({top_oil_temp.value:.2f}°C). Preserving raw sensor reading."
                            ),
                            field_name="hot_spot_temp_c",
                        )
                        step_issues.append(inv_issue)
                        all_issues.append(inv_issue)
                else:
                    hot_spot_rise = None
            elif delta_hs_prev is not None and parameters_valid and top_oil_temp is not None:
                # Modeled hot-spot state
                hot_spot_rise = Measurement(
                    value=delta_hs_prev,
                    unit="K",
                    evidence=EvidenceClassification.MODELED,
                    quality=MeasurementQuality.GOOD,
                    timestamp=ts_k,
                )
                hot_spot_temp = Measurement(
                    value=top_oil_temp.value + delta_hs_prev,
                    unit="°C",
                    evidence=EvidenceClassification.MODELED,
                    quality=MeasurementQuality.GOOD,
                    timestamp=ts_k,
                )
            else:
                hot_spot_temp = None
                hot_spot_rise = None

            # ------------------------------------------------------------------
            # 3.3 Independent Degradation Rates (F_AA and V)
            # ------------------------------------------------------------------
            faa_meas: Optional[Measurement[float]] = None
            v_meas: Optional[Measurement[float]] = None
            faa_ref_t: Optional[float] = None
            v_ref_t: Optional[float] = None

            if hot_spot_temp is not None:
                # Evidence propagation:
                # MEASURED hot spot -> CALCULATED aging rate
                # MODELED hot spot  -> MODELED aging rate
                rate_evidence = (
                    EvidenceClassification.CALCULATED
                    if hot_spot_temp.evidence == EvidenceClassification.MEASURED
                    else EvidenceClassification.MODELED
                )

                # IEEE F_AA
                faa_val, faa_err, faa_ref_t = calculate_ieee_aging_acceleration_factor(
                    hot_spot_temp.value,
                    input_data.insulation_system,
                    stage=STAGE_NAME,
                )
                if faa_err is not None:
                    step_issues.append(faa_err)
                    all_issues.append(faa_err)
                if faa_val is not None:
                    faa_meas = Measurement(
                        value=faa_val,
                        unit="",
                        evidence=rate_evidence,
                        quality=MeasurementQuality.GOOD,
                        timestamp=ts_k,
                    )

                # IEC V
                v_val, v_err, v_ref_t = calculate_iec_relative_ageing_rate(
                    hot_spot_temp.value,
                    input_data.insulation_system,
                    stage=STAGE_NAME,
                )
                if v_err is not None:
                    step_issues.append(v_err)
                    all_issues.append(v_err)
                if v_val is not None:
                    v_meas = Measurement(
                        value=v_val,
                        unit="",
                        evidence=rate_evidence,
                        quality=MeasurementQuality.GOOD,
                        timestamp=ts_k,
                    )

            # ------------------------------------------------------------------
            # 3.4 Forward-Interval Loss-of-Life Contribution
            # ------------------------------------------------------------------
            interval_lol_meas: Optional[Measurement[float]] = None
            ts_end = timestamps[k + 1] if k < n_samples - 1 else ts_k

            if k < n_samples - 1:
                # Forward interval [t_k, t_{k+1})
                if aging_standard_valid and not is_gap and not is_chronology_break:
                    selected_rate = faa_meas if aging_standard == AgingStandardPreference.IEEE else v_meas
                    if selected_rate is not None and selected_rate.value is not None:
                        lol_increment = selected_rate.value * dt_k_hours
                        interval_lol_meas = Measurement(
                            value=lol_increment,
                            unit="h",
                            evidence=selected_rate.evidence,
                            quality=MeasurementQuality.GOOD,
                            timestamp=ts_k,
                        )
                    else:
                        has_incomplete_interval = True
                else:
                    has_incomplete_interval = True
            else:
                # Final sample: contributes zero duration
                interval_lol_meas = Measurement(
                    value=0.0,
                    unit="h",
                    evidence=(
                        faa_meas.evidence
                        if aging_standard == AgingStandardPreference.IEEE and faa_meas
                        else (v_meas.evidence if v_meas else EvidenceClassification.UNKNOWN)
                    ),
                    quality=MeasurementQuality.GOOD,
                    timestamp=ts_k,
                )

            forward_result = ThermalIntervalResult(
                timestamp_start=ts_k,
                timestamp_end=ts_end,
                duration_hours=dt_k_hours,
                equivalent_aging_hours=interval_lol_meas,
                is_continuity_break=(is_gap or is_chronology_break),
                is_quarantined=is_quarantined,
            )

            # ------------------------------------------------------------------
            # 3.5 State Propagation for Next Step k+1
            # ------------------------------------------------------------------
            if k < n_samples - 1:
                if not is_gap and not is_chronology_break and parameters_valid:
                    # Evaluate ultimate rises under loading k_loading
                    if model_standard == ThermalModelStandard.IEEE:
                        oil_u = calculate_ieee_ultimate_top_oil_rise(
                            k_loading,
                            parameters.rated_top_oil_rise_k.value,
                            parameters.loss_ratio_r.value,
                            parameters.oil_exponent_x.value,
                        )
                        hs_u = calculate_ieee_ultimate_hot_spot_rise(
                            k_loading,
                            parameters.rated_hot_spot_rise_k.value,
                            parameters.winding_exponent_y.value,
                        )
                    else:
                        oil_u = calculate_iec_ultimate_top_oil_rise(
                            k_loading,
                            parameters.rated_top_oil_rise_k.value,
                            parameters.loss_ratio_r.value,
                            parameters.oil_exponent_x.value,
                        )
                        if parameters.rated_hot_spot_rise_k is not None:
                            rated_hs = parameters.rated_hot_spot_rise_k.value
                        else:
                            rated_hs = parameters.hot_spot_factor_h.value * parameters.winding_to_oil_gradient_g.value
                        hs_u = calculate_iec_ultimate_hot_spot_rise(
                            k_loading,
                            rated_hs,
                            parameters.winding_exponent_y.value,
                        )

                    # Current rises to propagate
                    cur_oil_rise = top_oil_rise.value if top_oil_rise else delta_oil_prev
                    cur_hs_rise = hot_spot_rise.value if hot_spot_rise else delta_hs_prev

                    if cur_oil_rise is not None:
                        delta_oil_prev = solve_exponential_recurrence(
                            cur_oil_rise,
                            oil_u,
                            dt_k_hours,
                            parameters.time_constant_oil_hours.value,
                        )
                    else:
                        delta_oil_prev = None

                    if cur_hs_rise is not None:
                        delta_hs_prev = solve_exponential_recurrence(
                            cur_hs_rise,
                            hs_u,
                            dt_k_hours,
                            parameters.time_constant_winding_hours.value,
                        )
                    else:
                        delta_hs_prev = None
                else:
                    # Continuity gap, chronology break, or unvalidated parameters severs state
                    delta_oil_prev = None
                    delta_hs_prev = None

            # Calculation provenance record
            provenance: Dict[str, Any] = {
                "engine_version": self.engine_version,
                "asset_id": input_data.asset_id,
                "thermal_model_standard": (
                    model_standard.value if hasattr(model_standard, "value") else str(model_standard)
                    if model_standard else None
                ),
                "aging_standard": (
                    aging_standard.value if hasattr(aging_standard, "value") else str(aging_standard)
                    if aging_standard else None
                ),
                "insulation_system": (
                    input_data.insulation_system.value
                    if hasattr(input_data.insulation_system, "value")
                    else str(input_data.insulation_system)
                ),
                "faa_standard": "IEEE Std C57.91-2011 Clause 5",
                "v_standard": "IEC 60076-7:2018 Clause 6",
                "faa_reference_temperature_c": faa_ref_t,
                "v_reference_temperature_c": v_ref_t,
                "loading_ratio_pu": k_loading,
                "continuity_tolerance_seconds": input_data.continuity_tolerance_seconds,
            }

            step_res = ThermalStateResult(
                is_computed=(top_oil_temp is not None or hot_spot_temp is not None or faa_meas is not None),
                top_oil_temp_c=top_oil_temp,
                hot_spot_temp_c=hot_spot_temp,
                ambient_temp_c=amb_meas,
                top_oil_rise_k=top_oil_rise,
                hot_spot_rise_k=hot_spot_rise,
                aging_acceleration_factor_faa=faa_meas,
                relative_ageing_rate_v=v_meas,
                aging_acceleration_factor=faa_meas if aging_standard == AgingStandardPreference.IEEE else v_meas,
                forward_interval_result=forward_result,
                timestamp=ts_k,
                asset_id=input_data.asset_id,
                thermal_model_standard=model_standard if isinstance(model_standard, ThermalModelStandard) else None,
                aging_standard=aging_standard if isinstance(aging_standard, AgingStandardPreference) else None,
                insulation_system=input_data.insulation_system,
                faa_reference_temperature_c=faa_ref_t,
                v_reference_temperature_c=v_ref_t,
                is_continuity_break=(is_gap or is_chronology_break),
                is_thermal_quarantined=is_quarantined,
                issues=step_issues,
                calculation_provenance=provenance,
            )
            step_results.append(step_res)

        # ----------------------------------------------------------------------
        # 4. Batch-Level Cumulative Loss-of-Life Resolution
        # ----------------------------------------------------------------------
        cum_lol_meas: Optional[Measurement[float]] = None
        lol_percent_meas: Optional[Measurement[float]] = None
        ref_life_val: Optional[float] = None
        is_complete: bool = (
            not has_incomplete_interval
            and not has_chronology_error
            and aging_standard_valid
        )

        if has_incomplete_interval or has_chronology_error or not aging_standard_valid:
            inc_issue = ProcessingIssue(
                stage=STAGE_NAME,
                severity=IssueSeverity.WARNING,
                code=WARN_INCOMPLETE_INTEGRATION_WINDOW,
                message=(
                    "Evaluation window contains unobserved telemetry gaps, chronological errors "
                    "(duplicate/out-of-order timestamps), quarantined intervals, or unconfigured "
                    "aging standard. Cumulative equivalent aging hours and loss of life percentage "
                    "cannot be speculatively calculated and are set to UNKNOWN."
                ),
                field_name="cumulative_aging_hours",
            )
            all_issues.append(inc_issue)
            for sr in step_results:
                sr.issues.append(inc_issue)
        else:
            # Sum up valid intervals
            total_eq_hours = 0.0
            cum_evidence = EvidenceClassification.CALCULATED
            for sr in step_results:
                if (
                    sr.forward_interval_result
                    and sr.forward_interval_result.equivalent_aging_hours
                    and sr.forward_interval_result.equivalent_aging_hours.value is not None
                ):
                    total_eq_hours += sr.forward_interval_result.equivalent_aging_hours.value
                    if sr.forward_interval_result.equivalent_aging_hours.evidence == EvidenceClassification.MODELED:
                        cum_evidence = EvidenceClassification.MODELED

            cum_lol_meas = Measurement(
                value=total_eq_hours,
                unit="h",
                evidence=cum_evidence,
                quality=MeasurementQuality.GOOD,
                timestamp=timestamps[-1],
            )

            # Normalization against validated reference life
            if parameters is not None and parameters.reference_life_hours is not None:
                if parameters.reference_life_hours.is_approved_for_high_consequence():
                    ref_life_val = float(parameters.reference_life_hours.value)
                    pct_val = (total_eq_hours / ref_life_val) * 100.0
                    lol_percent_meas = Measurement(
                        value=pct_val,
                        unit="%",
                        evidence=cum_evidence,
                        quality=MeasurementQuality.GOOD,
                        timestamp=timestamps[-1],
                    )
                else:
                    ref_issue = ProcessingIssue(
                        stage=STAGE_NAME,
                        severity=IssueSeverity.WARNING,
                        code=WARN_UNCONFIGURED_REFERENCE_LIFE,
                        message=(
                            "Reference life parameter is unverified or has unapproved source class. "
                            "Loss-of-life percentage will remain UNKNOWN."
                        ),
                        field_name="loss_of_life_percent",
                    )
                    all_issues.append(ref_issue)
                    for sr in step_results:
                        sr.issues.append(ref_issue)
            else:
                ref_issue = ProcessingIssue(
                    stage=STAGE_NAME,
                    severity=IssueSeverity.WARNING,
                    code=WARN_UNCONFIGURED_REFERENCE_LIFE,
                    message=(
                        "No asset-specific reference insulation life configured. "
                        "Universal 180,000-hour fallback is prohibited. Loss-of-life percentage is UNKNOWN."
                    ),
                    field_name="loss_of_life_percent",
                )
                all_issues.append(ref_issue)
                for sr in step_results:
                    sr.issues.append(ref_issue)

        # Update step results with cumulative batch values
        final_results: List[ThermalStateResult] = []
        for sr in step_results:
            updated = ThermalStateResult(
                is_computed=sr.is_computed,
                top_oil_temp_c=sr.top_oil_temp_c,
                hot_spot_temp_c=sr.hot_spot_temp_c,
                ambient_temp_c=sr.ambient_temp_c,
                top_oil_rise_k=sr.top_oil_rise_k,
                hot_spot_rise_k=sr.hot_spot_rise_k,
                aging_acceleration_factor_faa=sr.aging_acceleration_factor_faa,
                relative_ageing_rate_v=sr.relative_ageing_rate_v,
                aging_acceleration_factor=sr.aging_acceleration_factor,
                forward_interval_result=sr.forward_interval_result,
                equivalent_loss_of_life_hours=cum_lol_meas,
                cumulative_aging_hours=cum_lol_meas,
                loss_of_life_percent=lol_percent_meas,
                reference_life_hours=ref_life_val,
                is_integration_complete=is_complete,
                timestamp=sr.timestamp,
                asset_id=sr.asset_id,
                thermal_model_standard=sr.thermal_model_standard,
                aging_standard=sr.aging_standard,
                insulation_system=sr.insulation_system,
                faa_reference_temperature_c=sr.faa_reference_temperature_c,
                v_reference_temperature_c=sr.v_reference_temperature_c,
                is_continuity_break=sr.is_continuity_break,
                is_thermal_quarantined=sr.is_thermal_quarantined,
                issues=sr.issues,
                calculation_provenance=sr.calculation_provenance,
            )
            final_results.append(updated)

        return final_results, all_issues
