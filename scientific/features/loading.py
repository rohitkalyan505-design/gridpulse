"""
GridPulse — Transformer Loading & Overload Analytics Engine
Part of scientific.features.

Phase 2 Step 4: Overall Transformer Loading & Overload Analytics.
Provides:
1. Canonical kVA normalization: L = S_actual_kVA / S_rated_kVA.
2. Deterministic screening-band classification:
   LIGHT (0.00 <= L < 0.30), NORMAL (0.30 <= L <= 0.80),
   ELEVATED (0.80 < L <= continuous_threshold),
   CONTINUOUS_OVERLOAD (continuous_threshold < L <= emergency_threshold),
   EMERGENCY_OVERLOAD (L > emergency_threshold).
3. Strict configuration invariants:
   0 < continuous_threshold < emergency_threshold
   0.80 <= continuous_threshold < emergency_threshold
4. Forward-interval sample-and-hold time-weighted average loading:
   L_k governs [t_k, t_{k+1}); delta_t_k = t_{k+1} - t_k; final delta_t_N = 0.
   No trapezoidal or linear interpolation.
5. Peak loading ratio, timestamp, and apparent power tracking.
6. Deterministic overload cycles and telemetry continuity break detection.
7. Coexistence of measured vs calculated apparent power from Step 3.
8. EvidenceClassification.CALCULATED and comprehensive structured provenance.

MANDATORY SCIENTIFIC QUALIFICATION:
"1.4 pu is the GridPulse default screening convention when no asset-specific
emergency threshold is configured. It is not a universal physical emergency
limit established for every transformer by the cited standards."
Citations to IEC 60076-7 and IEEE C57.91 represent engineering reference
context only in Step 4; thermal validation is deferred to Phase 2 Step 5.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple
import uuid

from scientific.contracts.asset import TransformerAssetSpec, validate_loading_thresholds
from scientific.contracts.enums import (
    EvidenceClassification,
    IssueSeverity,
    LoadingState,
    MeasurementQuality,
    OverloadSeverity,
)
from scientific.contracts.issues import ProcessingIssue
from scientific.contracts.measurement import CANONICAL_UNITS, Measurement
from scientific.contracts.results import (
    ElectricalFeaturesResult,
    OverloadCycle,
    TransformerLoadingResult,
)


# ==============================================================================
# Constants and Standards Documentation
# ==============================================================================

DEFAULT_EMERGENCY_SCREENING_QUALIFICATION = (
    "1.4 pu is the GridPulse default screening convention when no asset-specific "
    "emergency threshold is configured. It is not a universal physical emergency "
    "limit established for every transformer by the cited standards."
)

CLASSIFICATION_SCREENING_CONVENTIONS = (
    "The 0.30 and 0.80 pu boundaries are GridPulse configurable screening conventions "
    "used to segment asset utilization regimes. Continuous and emergency thresholds "
    "are active asset operational limits."
)

DEFAULT_NOMINAL_INTERVAL_SECONDS = 300.0  # Standard 5-minute telemetry cadence
DEFAULT_MAX_GAP_MULTIPLIER = 2.0          # max_gap = 2 * nominal_interval_seconds
NEAR_ZERO_RATED_POWER_THRESHOLD_KVA = 1.0


# ==============================================================================
# Unit Normalization Helpers
# ==============================================================================

def normalize_apparent_power_to_canonical_kva(
    apparent_power: Measurement[float],
) -> Tuple[Optional[float], Optional[ProcessingIssue]]:
    """
    Normalizes an apparent power measurement from its native unit (VA, kVA, MVA)
    to canonical kVA.

    Returns:
        (canonical_kva_value, optional_issue)
    """
    if apparent_power is None or apparent_power.value is None:
        return None, ProcessingIssue(
            stage="loading_analysis",
            severity=IssueSeverity.WARNING,
            code="ERR_INSUFFICIENT_TELEMETRY",
            message="Apparent power measurement is missing or None.",
            field_name="apparent_power",
        )

    val = apparent_power.value
    if not isinstance(val, (int, float)) or not math.isfinite(val):
        return None, ProcessingIssue(
            stage="loading_analysis",
            severity=IssueSeverity.CRITICAL,
            code="ERR_NON_FINITE_INPUT",
            message=f"Apparent power value must be finite, got: {val}",
            field_name="apparent_power",
        )

    if val < 0.0:
        return None, ProcessingIssue(
            stage="loading_analysis",
            severity=IssueSeverity.CRITICAL,
            code="ERR_PHYSICAL_DOMAIN_VIOLATION",
            message=f"Apparent power cannot be negative, got {val} {apparent_power.unit}.",
            field_name="apparent_power",
        )

    unit = (apparent_power.unit or "kVA").strip()
    unit_lower = unit.lower()

    if unit_lower == "kva":
        return float(val), None
    elif unit_lower == "va":
        return float(val) / 1000.0, None
    elif unit_lower == "mva":
        return float(val) * 1000.0, None
    else:
        # Check canonical unit metadata
        meta = CANONICAL_UNITS.get(unit)
        if meta and meta.dimension == "apparent_power":
            # Native scaling
            if meta.canonical_unit == "kVA":
                return float(val), None

        return None, ProcessingIssue(
            stage="loading_analysis",
            severity=IssueSeverity.CRITICAL,
            code="ERR_INCOMPATIBLE_UNIT",
            message=f"Incompatible unit '{unit}' for apparent power. Expected VA, kVA, or MVA.",
            field_name="apparent_power.unit",
        )


# ==============================================================================
# Deterministic Screening-Band Classification
# ==============================================================================

def classify_loading_state(
    loading_ratio: float,
    continuous_threshold: float,
    emergency_threshold: float,
) -> LoadingState:
    """
    Classifies a per-unit loading ratio into deterministic screening bands:
    - LIGHT:               0.00 <= L < 0.30
    - NORMAL:              0.30 <= L <= 0.80
    - ELEVATED:            0.80 < L <= continuous_threshold
    - CONTINUOUS_OVERLOAD: continuous_threshold < L <= emergency_threshold
    - EMERGENCY_OVERLOAD:  L > emergency_threshold
    """
    if loading_ratio < 0.30:
        return LoadingState.LIGHT
    elif loading_ratio <= 0.80:
        return LoadingState.NORMAL
    elif loading_ratio <= continuous_threshold:
        return LoadingState.ELEVATED
    elif loading_ratio <= emergency_threshold:
        return LoadingState.CONTINUOUS_OVERLOAD
    else:
        return LoadingState.EMERGENCY_OVERLOAD


# ==============================================================================
# Single Record Loading Derivation
# ==============================================================================

def calculate_record_loading(
    apparent_power: Measurement[float],
    asset_spec: TransformerAssetSpec,
    timestamp: Optional[datetime] = None,
    calculation_provenance_extra: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[TransformerLoadingResult], List[ProcessingIssue]]:
    """
    Derives deterministic overall transformer loading metrics for a single observation.
    Guarantees:
    - Overall transformer loading only (zero per-phase fields).
    - EvidenceClassification.CALCULATED on all derived measurements.
    - Preserves measured vs calculated apparent power coexistence.
    - Enforces configuration invariants on thresholds and rated capacity.
    """
    issues: List[ProcessingIssue] = []

    # 1. Validate asset specification rated capacity
    if asset_spec is None:
        issue = ProcessingIssue(
            stage="loading_analysis",
            severity=IssueSeverity.CRITICAL,
            code="ERR_INSUFFICIENT_TELEMETRY",
            message="TransformerAssetSpec is required for loading analysis.",
            field_name="asset_spec",
        )
        return None, [issue]

    rated_kva = asset_spec.rated_power_kva
    if not isinstance(rated_kva, (int, float)) or not math.isfinite(rated_kva) or rated_kva <= 0.0:
        issue = ProcessingIssue(
            stage="loading_analysis",
            severity=IssueSeverity.CRITICAL,
            code="ERR_NON_POSITIVE_RATED_CAPACITY",
            message=f"Asset rated capacity must be strictly positive and finite, got: {rated_kva}",
            field_name="asset_spec.rated_power_kva",
        )
        return None, [issue]

    if rated_kva < NEAR_ZERO_RATED_POWER_THRESHOLD_KVA:
        issues.append(
            ProcessingIssue(
                stage="loading_analysis",
                severity=IssueSeverity.WARNING,
                code="WARN_NEAR_ZERO_RATED_POWER",
                message=f"Transformer rated capacity {rated_kva} kVA is unusually small (< 1.0 kVA).",
                field_name="asset_spec.rated_power_kva",
            )
        )

    # 2. Validate loading threshold invariants
    limits = asset_spec.operational_limits
    cont_thresh = limits.max_continuous_loading_pu
    emerg_thresh = limits.emergency_loading_pu

    is_valid_thresh, thresh_issue = validate_loading_thresholds(
        continuous_threshold=cont_thresh,
        emergency_threshold=emerg_thresh,
        asset_id=asset_spec.asset_id,
    )
    if not is_valid_thresh:
        # Preserve invalid configuration for diagnostics, do not silently substitute or clamp
        return None, [thresh_issue]

    # 3. Normalize apparent power to canonical kVA
    s_actual_kva, s_issue = normalize_apparent_power_to_canonical_kva(apparent_power)
    if s_issue is not None:
        issues.append(s_issue)
        if s_actual_kva is None:
            return None, issues

    # 4. Resolve effective calculation timestamp
    effective_ts = timestamp or apparent_power.timestamp
    if effective_ts.tzinfo is None:
        effective_ts = effective_ts.replace(tzinfo=timezone.utc)

    # 5. Calculate loading ratio (L = S_actual / S_rated) and percentage (L% = L * 100)
    loading_ratio = s_actual_kva / rated_kva
    loading_percent = loading_ratio * 100.0

    # 6. Deterministic screening-band classification
    state = classify_loading_state(loading_ratio, cont_thresh, emerg_thresh)
    is_overloaded = loading_ratio > cont_thresh
    is_emergency = loading_ratio > emerg_thresh

    # 7. Construct Provenance
    provenance = {
        "formula_id": "TRANSFORMER_LOADING_RATIO",
        "equation": "L = S_actual_kVA / S_rated_kVA",
        "asset_id": asset_spec.asset_id,
        "calculation_timestamp": datetime.now(timezone.utc).isoformat(),
        "input_apparent_power": {
            "value": apparent_power.value,
            "unit": apparent_power.unit,
            "evidence": apparent_power.evidence.value,
            "quality": apparent_power.quality.value,
            "canonical_kva": s_actual_kva,
        },
        "rated_power_kva": rated_kva,
        "threshold_configuration": {
            "continuous_threshold_pu": cont_thresh,
            "emergency_threshold_pu": emerg_thresh,
            "rule": "0.80 <= continuous_threshold < emergency_threshold",
        },
        "screening_conventions_note": CLASSIFICATION_SCREENING_CONVENTIONS,
        "emergency_threshold_qualification": DEFAULT_EMERGENCY_SCREENING_QUALIFICATION,
    }
    if calculation_provenance_extra:
        provenance.update(calculation_provenance_extra)

    # 8. Create typed Measurement objects with CALCULATED evidence
    m_loading_ratio = Measurement(
        value=loading_ratio,
        unit="pu",
        evidence=EvidenceClassification.CALCULATED,
        quality=apparent_power.quality,
        timestamp=effective_ts,
        metadata=provenance,
    )
    m_loading_percent = Measurement(
        value=loading_percent,
        unit="percent",
        evidence=EvidenceClassification.CALCULATED,
        quality=apparent_power.quality,
        timestamp=effective_ts,
        metadata=provenance,
    )
    m_apparent_power_kva = Measurement(
        value=s_actual_kva,
        unit="kVA",
        evidence=apparent_power.evidence,
        quality=apparent_power.quality,
        timestamp=effective_ts,
        metadata={"normalized_from": apparent_power.unit},
    )

    result = TransformerLoadingResult(
        is_computed=True,
        loading_ratio_pu=m_loading_ratio,
        loading_percent=m_loading_percent,
        loading_state=state,
        total_apparent_power_kva=m_apparent_power_kva,
        time_weighted_average_loading_pu=None,
        peak_loading_ratio_pu=m_loading_ratio,
        peak_loading_timestamp=effective_ts,
        is_overloaded=is_overloaded,
        is_emergency=is_emergency,
        total_overload_duration_seconds=0.0,
        overload_cycles=[],
        calculation_provenance=provenance,
    )

    return result, issues


# ==============================================================================
# Batch Loading & Time-Weighted Interval Analytics
# ==============================================================================

def calculate_batch_loading(
    features_list: List[ElectricalFeaturesResult],
    asset_spec: TransformerAssetSpec,
    nominal_interval_seconds: float = DEFAULT_NOMINAL_INTERVAL_SECONDS,
    max_gap_seconds: Optional[float] = None,
) -> Tuple[TransformerLoadingResult, List[ProcessingIssue]]:
    """
    Computes batch-level transformer loading analytics across a time window:
    1. Forward-interval sample-and-hold time-weighted average loading:
       L_k governs [t_k, t_{k+1}); delta_t_k = t_{k+1} - t_k.
       Final observation t_N contributes delta_t_N = 0.
       No trapezoidal or linear interpolation.
    2. Peak loading ratio, timestamp, and apparent power tracking.
    3. Deterministic overload cycles and continuity break detection.
    4. Structured ProcessingIssue diagnostics.

    Constraints:
    - Continuity is broken when delta_t > max_gap, or on BAD/OUT_OF_RANGE/MISSING quality.
    - Zero speculative bridging across gaps.
    """
    all_issues: List[ProcessingIssue] = []

    # 1. Validate asset specification rated capacity
    if asset_spec is None:
        issue = ProcessingIssue(
            stage="loading_analysis",
            severity=IssueSeverity.CRITICAL,
            code="ERR_INSUFFICIENT_TELEMETRY",
            message="TransformerAssetSpec is required for batch loading analysis.",
            field_name="asset_spec",
        )
        return TransformerLoadingResult(is_computed=False), [issue]

    rated_kva = asset_spec.rated_power_kva
    if not isinstance(rated_kva, (int, float)) or not math.isfinite(rated_kva) or rated_kva <= 0.0:
        issue = ProcessingIssue(
            stage="loading_analysis",
            severity=IssueSeverity.CRITICAL,
            code="ERR_NON_POSITIVE_RATED_CAPACITY",
            message=f"Asset rated capacity must be strictly positive and finite, got: {rated_kva}",
            field_name="asset_spec.rated_power_kva",
        )
        return TransformerLoadingResult(is_computed=False), [issue]

    if rated_kva < NEAR_ZERO_RATED_POWER_THRESHOLD_KVA:
        all_issues.append(
            ProcessingIssue(
                stage="loading_analysis",
                severity=IssueSeverity.WARNING,
                code="WARN_NEAR_ZERO_RATED_POWER",
                message=f"Transformer rated capacity {rated_kva} kVA is unusually small (< 1.0 kVA).",
                field_name="asset_spec.rated_power_kva",
            )
        )

    # 2. Validate loading threshold invariants
    limits = asset_spec.operational_limits
    cont_thresh = limits.max_continuous_loading_pu
    emerg_thresh = limits.emergency_loading_pu

    is_valid_thresh, thresh_issue = validate_loading_thresholds(
        continuous_threshold=cont_thresh,
        emergency_threshold=emerg_thresh,
        asset_id=asset_spec.asset_id,
    )
    if not is_valid_thresh:
        # Preserve invalid configuration for diagnostics, do not silently substitute or clamp
        return TransformerLoadingResult(is_computed=False), [thresh_issue]

    if not features_list:
        return TransformerLoadingResult(is_computed=False), all_issues

    max_gap = (
        max_gap_seconds
        if max_gap_seconds is not None
        else (DEFAULT_MAX_GAP_MULTIPLIER * nominal_interval_seconds)
    )

    # 3. Extract and evaluate loading for each record
    unusable_qualities = {
        MeasurementQuality.BAD,
        MeasurementQuality.OUT_OF_RANGE,
        MeasurementQuality.MISSING,
    }

    evaluated_records: List[Dict[str, Any]] = []

    for idx, feat in enumerate(features_list):
        s_meas = feat.apparent_power_kva if feat else None
        if s_meas is None:
            evaluated_records.append({
                "is_usable": False,
                "timestamp": None,
                "loading_ratio": None,
                "s_actual_kva": None,
                "quality": MeasurementQuality.MISSING,
                "issue": ProcessingIssue(
                    stage="loading_analysis",
                    severity=IssueSeverity.WARNING,
                    code="ERR_INSUFFICIENT_TELEMETRY",
                    message=f"Record at index {idx} lacks apparent power measurement.",
                    field_name="apparent_power_kva",
                ),
            })
            continue

        ts = s_meas.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # Quality check
        if s_meas.quality in unusable_qualities or s_meas.evidence == EvidenceClassification.UNKNOWN:
            evaluated_records.append({
                "is_usable": False,
                "timestamp": ts,
                "loading_ratio": None,
                "s_actual_kva": None,
                "quality": s_meas.quality,
                "issue": None,
            })
            continue

        s_val, s_issue = normalize_apparent_power_to_canonical_kva(s_meas)
        if s_issue is not None:
            all_issues.append(s_issue)
            evaluated_records.append({
                "is_usable": False,
                "timestamp": ts,
                "loading_ratio": None,
                "s_actual_kva": None,
                "quality": s_meas.quality,
                "issue": s_issue,
            })
            continue

        l_ratio = s_val / rated_kva
        evaluated_records.append({
            "is_usable": True,
            "timestamp": ts,
            "loading_ratio": l_ratio,
            "s_actual_kva": s_val,
            "quality": s_meas.quality,
            "issue": None,
        })

    # 4. Compute Forward-Interval Sample-and-Hold Time-Weighted Average
    # Formula: SUM(L_k * delta_t_k) / SUM(delta_t_k)
    # L_k governs [t_k, t_{k+1}); delta_t_N = 0.
    # No trapezoidal or linear interpolation.
    total_weighted_loading = 0.0
    total_valid_duration_seconds = 0.0

    n_records = len(evaluated_records)
    for k in range(n_records - 1):
        curr = evaluated_records[k]
        next_rec = evaluated_records[k + 1]

        # Break continuity if either current or next record is unusable
        if not curr["is_usable"] or not next_rec["is_usable"]:
            continue

        t_curr = curr["timestamp"]
        t_next = next_rec["timestamp"]
        if t_curr is None or t_next is None:
            continue

        delta_t = (t_next - t_curr).total_seconds()

        # Strict forward-interval bounds check: 0 < delta_t <= max_gap
        if 0 < delta_t <= max_gap:
            total_weighted_loading += curr["loading_ratio"] * delta_t
            total_valid_duration_seconds += delta_t
        # else: interval exceeds max_gap or non-positive, excluded without bridging

    time_weighted_avg = None
    if total_valid_duration_seconds > 0:
        time_weighted_avg = total_weighted_loading / total_valid_duration_seconds

    # 5. Calculate Peak Loading (from usable records only)
    peak_ratio = None
    peak_ts = None
    peak_s_kva = None

    for rec in evaluated_records:
        if not rec["is_usable"] or rec["loading_ratio"] is None:
            continue
        lr = rec["loading_ratio"]
        if peak_ratio is None or lr > peak_ratio:
            peak_ratio = lr
            peak_ts = rec["timestamp"]
            peak_s_kva = rec["s_actual_kva"]

    # 6. Deterministic Overload Cycles and Continuity Breaks
    # Overload begins when L_k > continuous_threshold.
    # Accumulate forward intervals where continuous overload is actually observed.
    # Terminate normally when L_(k+1) <= continuous_threshold.
    # Break continuity when delta_t > max_gap or bad/missing telemetry occurs.
    overload_cycles: List[OverloadCycle] = []
    active_cycle_start: Optional[datetime] = None
    active_cycle_last_ts: Optional[datetime] = None
    active_cycle_duration: float = 0.0
    active_cycle_peak_ratio: float = 0.0
    active_cycle_peak_s_kva: float = 0.0

    cycle_index = 1

    for k in range(n_records):
        rec = evaluated_records[k]
        is_usable = rec["is_usable"]
        l_ratio = rec["loading_ratio"]
        ts = rec["timestamp"]
        s_kva = rec["s_actual_kva"]

        is_overloaded = is_usable and (l_ratio is not None) and (l_ratio > cont_thresh)

        if active_cycle_start is None:
            # Not in an active cycle: check if a new cycle starts
            if is_overloaded:
                active_cycle_start = ts
                active_cycle_last_ts = ts
                active_cycle_duration = 0.0
                active_cycle_peak_ratio = l_ratio
                active_cycle_peak_s_kva = s_kva
        else:
            # Active cycle is running: evaluate forward transition from k-1 to k
            prev_rec = evaluated_records[k - 1]
            prev_ts = prev_rec["timestamp"]

            # Evaluate continuity of the interval from prev_ts to ts
            is_continuous_step = False
            delta_t = 0.0
            if is_usable and prev_rec["is_usable"] and prev_ts is not None and ts is not None:
                delta_t = (ts - prev_ts).total_seconds()
                if 0 < delta_t <= max_gap:
                    is_continuous_step = True

            if is_continuous_step:
                # Forward interval governed by prev_rec was continuous
                active_cycle_duration += delta_t
                active_cycle_last_ts = ts

                if is_overloaded:
                    # Overload continues at record k
                    if l_ratio > active_cycle_peak_ratio:
                        active_cycle_peak_ratio = l_ratio
                        active_cycle_peak_s_kva = s_kva
                else:
                    # Load dropped to normal/elevated (L_k <= cont_thresh): normal termination
                    severity = (
                        OverloadSeverity.EMERGENCY_OVERLOAD
                        if active_cycle_peak_ratio > emerg_thresh
                        else OverloadSeverity.CONTINUOUS_OVERLOAD
                    )
                    cycle_id = f"OLC-{asset_spec.asset_id}-{active_cycle_start.strftime('%Y%m%d%H%M%S')}-{cycle_index:03d}"
                    cycle_index += 1
                    overload_cycles.append(
                        OverloadCycle(
                            cycle_id=cycle_id,
                            start_time=active_cycle_start,
                            end_time=ts,
                            duration_seconds=active_cycle_duration,
                            peak_loading_ratio_pu=active_cycle_peak_ratio,
                            peak_apparent_power_kva=active_cycle_peak_s_kva,
                            severity=severity,
                            continuity_break_detected=False,
                        )
                    )
                    active_cycle_start = None
                    active_cycle_last_ts = None
            else:
                # Continuity broken (gap > max_gap, or current record is bad/missing/unusable)
                # Close cycle at last valid observed overloaded timestamp
                severity = (
                    OverloadSeverity.EMERGENCY_OVERLOAD
                    if active_cycle_peak_ratio > emerg_thresh
                    else OverloadSeverity.CONTINUOUS_OVERLOAD
                )
                cycle_id = f"OLC-{asset_spec.asset_id}-{active_cycle_start.strftime('%Y%m%d%H%M%S')}-{cycle_index:03d}"
                cycle_index += 1
                overload_cycles.append(
                    OverloadCycle(
                        cycle_id=cycle_id,
                        start_time=active_cycle_start,
                        end_time=active_cycle_last_ts,
                        duration_seconds=active_cycle_duration,
                        peak_loading_ratio_pu=active_cycle_peak_ratio,
                        peak_apparent_power_kva=active_cycle_peak_s_kva,
                        severity=severity,
                        continuity_break_detected=True,
                    )
                )
                all_issues.append(
                    ProcessingIssue(
                        stage="loading_analysis",
                        severity=IssueSeverity.WARNING,
                        code="WARN_TELEMETRY_CONTINUITY_BREAK",
                        message=(
                            f"Telemetry continuity break detected during active overload cycle {cycle_id}. "
                            f"Cycle closed at {active_cycle_last_ts.isoformat()} without bridging unobserved gap."
                        ),
                        field_name="overload_cycles",
                        timestamp=ts if ts else active_cycle_last_ts,
                    )
                )

                # Reset active cycle
                active_cycle_start = None
                active_cycle_last_ts = None

                # If current record is valid and overloaded, start a fresh new cycle
                if is_overloaded:
                    active_cycle_start = ts
                    active_cycle_last_ts = ts
                    active_cycle_duration = 0.0
                    active_cycle_peak_ratio = l_ratio
                    active_cycle_peak_s_kva = s_kva

    # If cycle remains open at the end of the batch, close it at window boundary
    if active_cycle_start is not None and active_cycle_last_ts is not None:
        severity = (
            OverloadSeverity.EMERGENCY_OVERLOAD
            if active_cycle_peak_ratio > emerg_thresh
            else OverloadSeverity.CONTINUOUS_OVERLOAD
        )
        cycle_id = f"OLC-{asset_spec.asset_id}-{active_cycle_start.strftime('%Y%m%d%H%M%S')}-{cycle_index:03d}"
        overload_cycles.append(
            OverloadCycle(
                cycle_id=cycle_id,
                start_time=active_cycle_start,
                end_time=active_cycle_last_ts,
                duration_seconds=active_cycle_duration,
                peak_loading_ratio_pu=active_cycle_peak_ratio,
                peak_apparent_power_kva=active_cycle_peak_s_kva,
                severity=severity,
                continuity_break_detected=False,
            )
        )

    total_overload_duration = sum(c.duration_seconds for c in overload_cycles)
    batch_is_overloaded = len(overload_cycles) > 0 or (peak_ratio is not None and peak_ratio > cont_thresh)
    batch_is_emergency = any(c.severity == OverloadSeverity.EMERGENCY_OVERLOAD for c in overload_cycles) or (
        peak_ratio is not None and peak_ratio > emerg_thresh
    )

    # 7. Package Measurements & Result
    now_utc = datetime.now(timezone.utc)
    batch_ts = peak_ts or now_utc

    m_tw_avg = None
    if time_weighted_avg is not None:
        m_tw_avg = Measurement(
            value=time_weighted_avg,
            unit="pu",
            evidence=EvidenceClassification.CALCULATED,
            quality=MeasurementQuality.GOOD,
            timestamp=batch_ts,
            metadata={
                "formula_id": "FORWARD_INTERVAL_TIME_WEIGHTED_AVERAGE",
                "equation": "SUM(L_k * delta_t_k) / SUM(delta_t_k)",
                "total_valid_duration_seconds": total_valid_duration_seconds,
                "nominal_interval_seconds": nominal_interval_seconds,
                "max_gap_seconds": max_gap,
                "sample_count": len(evaluated_records),
            },
        )

    m_peak_loading = None
    if peak_ratio is not None:
        m_peak_loading = Measurement(
            value=peak_ratio,
            unit="pu",
            evidence=EvidenceClassification.CALCULATED,
            quality=MeasurementQuality.GOOD,
            timestamp=peak_ts,
            metadata={
                "formula_id": "PEAK_LOADING_RATIO",
                "peak_apparent_power_kva": peak_s_kva,
                "peak_loading_timestamp": peak_ts.isoformat(),
            },
        )

    # Resolve latest instantaneous loading state from the last usable record
    latest_loading_ratio = None
    latest_loading_percent = None
    latest_state = None
    latest_s_meas = None

    for rec in reversed(evaluated_records):
        if rec["is_usable"] and rec["loading_ratio"] is not None:
            latest_loading_ratio = rec["loading_ratio"]
            latest_loading_percent = rec["loading_ratio"] * 100.0
            latest_state = classify_loading_state(rec["loading_ratio"], cont_thresh, emerg_thresh)
            latest_s_meas = Measurement(
                value=rec["s_actual_kva"],
                unit="kVA",
                evidence=EvidenceClassification.CALCULATED,
                quality=rec["quality"],
                timestamp=rec["timestamp"],
            )
            break

    m_latest_ratio = None
    m_latest_percent = None
    if latest_loading_ratio is not None:
        m_latest_ratio = Measurement(
            value=latest_loading_ratio,
            unit="pu",
            evidence=EvidenceClassification.CALCULATED,
            quality=MeasurementQuality.GOOD,
            timestamp=batch_ts,
        )
        m_latest_percent = Measurement(
            value=latest_loading_percent,
            unit="percent",
            evidence=EvidenceClassification.CALCULATED,
            quality=MeasurementQuality.GOOD,
            timestamp=batch_ts,
        )

    batch_provenance = {
        "formula_id": "BATCH_TRANSFORMER_LOADING",
        "asset_id": asset_spec.asset_id,
        "calculation_timestamp": now_utc.isoformat(),
        "rated_power_kva": rated_kva,
        "threshold_configuration": {
            "continuous_threshold_pu": cont_thresh,
            "emergency_threshold_pu": emerg_thresh,
            "rule": "0.80 <= continuous_threshold < emergency_threshold",
        },
        "screening_conventions_note": CLASSIFICATION_SCREENING_CONVENTIONS,
        "emergency_threshold_qualification": DEFAULT_EMERGENCY_SCREENING_QUALIFICATION,
        "total_records_processed": n_records,
        "total_valid_duration_seconds": total_valid_duration_seconds,
        "nominal_interval_seconds": nominal_interval_seconds,
        "max_gap_seconds": max_gap,
        "overload_cycle_count": len(overload_cycles),
    }

    result = TransformerLoadingResult(
        is_computed=True,
        loading_ratio_pu=m_latest_ratio,
        loading_percent=m_latest_percent,
        loading_state=latest_state,
        total_apparent_power_kva=latest_s_meas,
        time_weighted_average_loading_pu=m_tw_avg,
        peak_loading_ratio_pu=m_peak_loading,
        peak_loading_timestamp=peak_ts,
        is_overloaded=batch_is_overloaded,
        is_emergency=batch_is_emergency,
        total_overload_duration_seconds=total_overload_duration,
        overload_cycles=overload_cycles,
        calculation_provenance=batch_provenance,
    )

    return result, all_issues
