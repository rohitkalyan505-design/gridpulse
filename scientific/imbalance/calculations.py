"""
GridPulse — Deterministic Phase Imbalance & Symmetrical Components Calculations
Part of Phase 2 Step 6.

Formulations:
1. Phase Magnitude Imbalance (Voltage and Current):
   - Arithmetic Mean Magnitude: X_mean = (Xa + Xb + Xc) / 3
   - Signed Deviations: Delta X_i = X_i - X_mean
   - Absolute Deviations: |Delta X_i|
   - Max Absolute Deviation: max(|Delta X_i|)
   - Percent Deviation: PVUR / CMUR = (max(|Delta X_i|) / X_mean) * 100%
   (Division by zero avoided: UNKNOWN returned when X_mean <= 0)

2. Fortescue Symmetrical Components (Valid Complex RMS Phasors):
   - Sequence operator: a = exp(j * 2*pi/3) = -0.5 + j*sqrt(3)/2
   - Sequence transformation (ABC positive-sequence convention):
     X0 = (Xa + Xb + Xc) / 3
     X1 = (Xa + a*Xb + a^2*Xc) / 3
     X2 = (Xa + a^2*Xb + a*Xc) / 3
   - Sequence transformation (ACB reverse-sequence convention):
     X0 = (Xa + Xb + Xc) / 3
     X1 = (Xa + a^2*Xb + a*Xc) / 3
     X2 = (Xa + a*Xb + a^2*Xc) / 3
   - Sequence ratios (when |X1| > epsilon):
     VUF = 100 * |V2| / |V1|  (IEC 61000-4-30 / IEC 60076)
     CUF = 100 * |I2| / |I1|
   - Neutral current (4-wire current phasors):
     In = -(Ia + Ib + Ic) = -3 * I0,  |In| = 3 * |I0|

3. Evidence-Grounded Derating:
   - Maximum phase current capacity method
   - Loss-based negative-sequence method (requires verified factory parameters)
   - Rejection of induction motor derating curves for static transformers
"""

import cmath
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple

from scientific.contracts.asset import OperationalLimits, TransformerAssetSpec
from scientific.contracts.enums import (
    DeratingMethod,
    EvidenceClassification,
    IssueSeverity,
    MeasurementQuality,
    PhaseIdentification,
    PhaseSequence,
    PhasorAngleConvention,
)
from scientific.contracts.issues import (
    ERR_DEGENERATE_POSITIVE_SEQUENCE,
    ERR_INCOMPLETE_THREE_PHASE_TELEMETRY,
    ERR_INVALID_PHASE_IDENTIFICATION,
    ERR_INVALID_PHASE_SEQUENCE,
    ERR_MISMATCHED_PHASE_TIMESTAMPS,
    ERR_MISSING_PHASOR_ANGLES,
    ProcessingIssue,
    WARN_CURRENT_UNBALANCE_EXCEEDS_LIMIT,
    WARN_DERATING_METHOD_UNAVAILABLE,
    WARN_UNVERIFIED_DERATING_PARAMETERS,
    WARN_VOLTAGE_UNBALANCE_EXCEEDS_LIMIT,
    WARN_ZERO_MEAN_MAGNITUDE,
)
from scientific.contracts.measurement import CANONICAL_UNITS, Measurement
from scientific.imbalance.contracts import (
    ComplexPhasor,
    DeratingAssessmentResult,
    DeratingConfiguration,
    PhaseMagnitudeImbalance,
    PhaseQuantity,
    SymmetricalComponentsResult,
    ThreePhaseQuantity,
)

# Fortescue complex rotation operator: a = exp(j * 2*pi/3)
OPERATOR_A: complex = cmath.exp(1j * 2.0 * math.pi / 3.0)
OPERATOR_A2: complex = OPERATOR_A * OPERATOR_A  # exp(j * 4*pi/3) = conj(a)

# Numerical threshold for positive-sequence denominator safety
NEAR_ZERO_SEQUENCE_THRESHOLD: float = 1e-6
RECONSTRUCTION_TOLERANCE: float = 1e-9


def calculate_phase_magnitude_imbalance(
    three_phase: ThreePhaseQuantity,
    quantity_type: str = "VOLTAGE",
    stage_name: str = "imbalance_analysis",
) -> Tuple[Optional[PhaseMagnitudeImbalance], List[ProcessingIssue]]:
    """
    Deterministic phase magnitude imbalance calculation for three-phase voltage or current.
    Calculates arithmetic mean magnitude, signed deviations, absolute deviations,
    maximum absolute deviation, and percentage deviation using the documented mean denominator.
    """
    issues: List[ProcessingIssue] = []
    ts = three_phase.timestamp or three_phase.phase_a.timestamp

    # 1. Check all three phases present and non-null
    p_a = three_phase.phase_a
    p_b = three_phase.phase_b
    p_c = three_phase.phase_c

    for phase_obj, p_name in [(p_a, "Phase A"), (p_b, "Phase B"), (p_c, "Phase C")]:
        if phase_obj is None or phase_obj.magnitude is None or phase_obj.magnitude.value is None:
            issues.append(
                ProcessingIssue(
                    stage=stage_name,
                    severity=IssueSeverity.WARNING,
                    code=ERR_INCOMPLETE_THREE_PHASE_TELEMETRY,
                    message=f"Missing telemetry magnitude for {p_name}. Imbalance calculation rejected.",
                    field_name=f"{quantity_type.lower()}_magnitude",
                    timestamp=ts,
                )
            )
            return None, issues

    val_a = p_a.magnitude.value
    val_b = p_b.magnitude.value
    val_c = p_c.magnitude.value

    # 2. Non-finite or negative magnitude checks
    for val, p_name in [(val_a, "Phase A"), (val_b, "Phase B"), (val_c, "Phase C")]:
        if not math.isfinite(val):
            issues.append(
                ProcessingIssue(
                    stage=stage_name,
                    severity=IssueSeverity.CRITICAL,
                    code="ERR_NON_FINITE_INPUT",
                    message=f"Non-finite magnitude {val} on {p_name}.",
                    field_name=f"{quantity_type.lower()}_magnitude",
                    timestamp=ts,
                )
            )
            return None, issues
        if val < 0.0:
            issues.append(
                ProcessingIssue(
                    stage=stage_name,
                    severity=IssueSeverity.CRITICAL,
                    code="ERR_PHYSICAL_BOUNDARY",
                    message=f"Negative magnitude {val} on {p_name} violates physical boundary.",
                    field_name=f"{quantity_type.lower()}_magnitude",
                    timestamp=ts,
                )
            )
            return None, issues

    # 3. Unit consistency check
    unit_a = p_a.magnitude.unit
    unit_b = p_b.magnitude.unit
    unit_c = p_c.magnitude.unit
    if not (unit_a == unit_b == unit_c):
        issues.append(
            ProcessingIssue(
                stage=stage_name,
                severity=IssueSeverity.CRITICAL,
                code="ERR_INCOMPATIBLE_UNITS",
                message=f"Mismatched phase units: Phase A='{unit_a}', Phase B='{unit_b}', Phase C='{unit_c}'.",
                field_name=f"{quantity_type.lower()}_magnitude",
                timestamp=ts,
            )
        )
        return None, issues

    # 4. Timestamp consistency check (phases must belong to same measurement window)
    ts_a = p_a.magnitude.timestamp
    ts_b = p_b.magnitude.timestamp
    ts_c = p_c.magnitude.timestamp
    max_ts_diff = max(
        abs((ts_a - ts_b).total_seconds()),
        abs((ts_b - ts_c).total_seconds()),
        abs((ts_a - ts_c).total_seconds()),
    )
    if max_ts_diff > 1.0:
        issues.append(
            ProcessingIssue(
                stage=stage_name,
                severity=IssueSeverity.CRITICAL,
                code=ERR_MISMATCHED_PHASE_TIMESTAMPS,
                message=(
                    f"Phase timestamps diverge by {max_ts_diff:.3f} s (> 1.0 s). "
                    f"Cannot combine asynchronous phase measurements."
                ),
                field_name=f"{quantity_type.lower()}_timestamp",
                timestamp=ts,
            )
        )
        return None, issues

    # 5. Arithmetic mean magnitude calculation
    mean_val = (val_a + val_b + val_c) / 3.0

    # Evidence & Quality propagation
    evidence = (
        EvidenceClassification.CALCULATED
        if all(
            p.magnitude.evidence in (EvidenceClassification.MEASURED, EvidenceClassification.CALCULATED)
            for p in (p_a, p_b, p_c)
        )
        else EvidenceClassification.MODELED
    )
    quality = (
        MeasurementQuality.SUSPECT
        if any(p.magnitude.quality == MeasurementQuality.SUSPECT for p in (p_a, p_b, p_c))
        else MeasurementQuality.GOOD
    )

    # Provenance dictionaries
    prov_base = {
        "formula": "(Xa + Xb + Xc) / 3",
        "quantity_type": quantity_type,
        "asset_id": three_phase.asset_id,
        "calculation_timestamp": ts.isoformat(),
    }

    mean_meas = Measurement(
        value=mean_val,
        unit=unit_a,
        evidence=evidence,
        quality=quality,
        timestamp=ts,
        metadata={**prov_base, "metric": "ARITHMETIC_MEAN_MAGNITUDE"},
    )

    # 6. Signed and absolute deviations
    dev_a = val_a - mean_val
    dev_b = val_b - mean_val
    dev_c = val_c - mean_val

    abs_a = abs(dev_a)
    abs_b = abs(dev_b)
    abs_c = abs(dev_c)

    deviations_signed = {
        "A": Measurement(
            value=dev_a,
            unit=unit_a,
            evidence=evidence,
            quality=quality,
            timestamp=ts,
            metadata={"phase": "A", "formula": "Xa - X_mean"},
        ),
        "B": Measurement(
            value=dev_b,
            unit=unit_a,
            evidence=evidence,
            quality=quality,
            timestamp=ts,
            metadata={"phase": "B", "formula": "Xb - X_mean"},
        ),
        "C": Measurement(
            value=dev_c,
            unit=unit_a,
            evidence=evidence,
            quality=quality,
            timestamp=ts,
            metadata={"phase": "C", "formula": "Xc - X_mean"},
        ),
    }

    deviations_absolute = {
        "A": Measurement(
            value=abs_a,
            unit=unit_a,
            evidence=evidence,
            quality=quality,
            timestamp=ts,
            metadata={"phase": "A", "formula": "|Xa - X_mean|"},
        ),
        "B": Measurement(
            value=abs_b,
            unit=unit_a,
            evidence=evidence,
            quality=quality,
            timestamp=ts,
            metadata={"phase": "B", "formula": "|Xb - X_mean|"},
        ),
        "C": Measurement(
            value=abs_c,
            unit=unit_a,
            evidence=evidence,
            quality=quality,
            timestamp=ts,
            metadata={"phase": "C", "formula": "|Xc - X_mean|"},
        ),
    }

    max_abs_dev = max(abs_a, abs_b, abs_c)
    max_dev_meas = Measurement(
        value=max_abs_dev,
        unit=unit_a,
        evidence=evidence,
        quality=quality,
        timestamp=ts,
        metadata={"formula": "max(|Delta Xa|, |Delta Xb|, |Delta Xc|)"},
    )

    # 7. Percentage deviation (Mean-based Denominator)
    percent_dev_meas: Optional[Measurement[float]] = None
    if mean_val <= 0.0:
        issues.append(
            ProcessingIssue(
                stage=stage_name,
                severity=IssueSeverity.WARNING,
                code=WARN_ZERO_MEAN_MAGNITUDE,
                message=(
                    f"Three-phase arithmetic mean magnitude is zero or non-positive ({mean_val} {unit_a}). "
                    f"Percentage deviation cannot be calculated. Division by zero avoided."
                ),
                field_name=f"{quantity_type.lower()}_mean_magnitude",
                timestamp=ts,
            )
        )
        percent_dev_meas = None
    else:
        pct_val = (max_abs_dev / mean_val) * 100.0
        percent_dev_meas = Measurement(
            value=pct_val,
            unit="percent",
            evidence=evidence,
            quality=quality,
            timestamp=ts,
            metadata={
                "formula": "(max_abs_deviation / mean_magnitude) * 100",
                "denominator": "THREE_PHASE_ARITHMETIC_MEAN",
                "metric_name": "PVUR" if quantity_type == "VOLTAGE" else "CMUR",
            },
        )

    return (
        PhaseMagnitudeImbalance(
            quantity_type=quantity_type,
            mean_magnitude=mean_meas,
            deviations_signed=deviations_signed,
            deviations_absolute=deviations_absolute,
            max_absolute_deviation=max_dev_meas,
            max_deviation_percent=percent_dev_meas,
            denominator_definition="THREE_PHASE_ARITHMETIC_MEAN",
            is_valid=True,
        ),
        issues,
    )


def calculate_symmetrical_components(
    three_phase: ThreePhaseQuantity,
    quantity_type: str = "VOLTAGE",
    stage_name: str = "symmetrical_components",
) -> Tuple[Optional[SymmetricalComponentsResult], List[ProcessingIssue]]:
    """
    Fortescue symmetrical-component transformation for valid three-phase complex RMS phasors.
    Transforms phase phasors (Xa, Xb, Xc) into sequence components (X0, X1, X2),
    verifies inverse reconstruction, computes negative-sequence unbalance ratio,
    and calculates neutral current for current phasors.
    """
    issues: List[ProcessingIssue] = []
    ts = three_phase.timestamp or three_phase.phase_a.timestamp

    # 1. Incomplete phase telemetry check
    if not three_phase.is_complete_three_phase:
        issues.append(
            ProcessingIssue(
                stage=stage_name,
                severity=IssueSeverity.WARNING,
                code=ERR_INCOMPLETE_THREE_PHASE_TELEMETRY,
                message="Incomplete three-phase telemetry. Symmetrical components cannot be calculated.",
                field_name=f"{quantity_type.lower()}_phasors",
                timestamp=ts,
            )
        )
        return None, issues

    # 2. Check for complex phasors (angles required)
    if not three_phase.has_complex_phasors:
        missing_angles = []
        if not three_phase.phase_a.is_phasor:
            missing_angles.append("Phase A")
        if not three_phase.phase_b.is_phasor:
            missing_angles.append("Phase B")
        if not three_phase.phase_c.is_phasor:
            missing_angles.append("Phase C")

        issues.append(
            ProcessingIssue(
                stage=stage_name,
                severity=IssueSeverity.WARNING,
                code=ERR_MISSING_PHASOR_ANGLES,
                message=(
                    f"Symmetrical components require valid complex phasors with phase angles. "
                    f"Missing angles for {', '.join(missing_angles)}. "
                    f"Magnitude-only inputs cannot fabricate symmetrical components."
                ),
                field_name=f"{quantity_type.lower()}_phasors",
                timestamp=ts,
            )
        )
        return None, issues

    # 3. Unit and timestamp consistency
    unit = three_phase.phase_a.unit
    if not (three_phase.phase_b.unit == unit == three_phase.phase_c.unit):
        issues.append(
            ProcessingIssue(
                stage=stage_name,
                severity=IssueSeverity.CRITICAL,
                code="ERR_INCOMPATIBLE_UNITS",
                message="Mismatched phase units across phasors.",
                field_name=f"{quantity_type.lower()}_phasors",
                timestamp=ts,
            )
        )
        return None, issues

    # 4. Extract complex phasors
    c_a = three_phase.phase_a.to_complex_phasor().as_complex
    c_b = three_phase.phase_b.to_complex_phasor().as_complex
    c_c = three_phase.phase_c.to_complex_phasor().as_complex

    seq = three_phase.phase_sequence
    if seq == PhaseSequence.ABC:
        # Standard positive-sequence ABC rotation:
        # X0 = (Xa + Xb + Xc) / 3
        # X1 = (Xa + a*Xb + a^2*Xc) / 3
        # X2 = (Xa + a^2*Xb + a*Xc) / 3
        x0 = (c_a + c_b + c_c) / 3.0
        x1 = (c_a + OPERATOR_A * c_b + OPERATOR_A2 * c_c) / 3.0
        x2 = (c_a + OPERATOR_A2 * c_b + OPERATOR_A * c_c) / 3.0

        # Reconstruction identity:
        # Xa = X0 + X1 + X2
        # Xb = X0 + a^2*X1 + a*X2
        # Xc = X0 + a*X1 + a^2*X2
        ca_rec = x0 + x1 + x2
        cb_rec = x0 + OPERATOR_A2 * x1 + OPERATOR_A * x2
        cc_rec = x0 + OPERATOR_A * x1 + OPERATOR_A2 * x2
    elif seq == PhaseSequence.ACB:
        # Reverse-sequence ACB rotation
        x0 = (c_a + c_b + c_c) / 3.0
        x1 = (c_a + OPERATOR_A2 * c_b + OPERATOR_A * c_c) / 3.0
        x2 = (c_a + OPERATOR_A * c_b + OPERATOR_A2 * c_c) / 3.0

        ca_rec = x0 + x1 + x2
        cb_rec = x0 + OPERATOR_A * x1 + OPERATOR_A2 * x2
        cc_rec = x0 + OPERATOR_A2 * x1 + OPERATOR_A * x2
    else:
        issues.append(
            ProcessingIssue(
                stage=stage_name,
                severity=IssueSeverity.CRITICAL,
                code=ERR_INVALID_PHASE_SEQUENCE,
                message=f"Unsupported phase sequence '{seq}'. Supported: ABC, ACB.",
                field_name="phase_sequence",
                timestamp=ts,
            )
        )
        return None, issues

    # 5. Reconstruction fidelity verification
    err_a = abs(c_a - ca_rec)
    err_b = abs(c_b - cb_rec)
    err_c = abs(c_c - cc_rec)
    max_recon_err = max(err_a, err_b, err_c)

    # 6. Magnitudes and Phase Angles
    mag_0 = abs(x0)
    mag_1 = abs(x1)
    mag_2 = abs(x2)

    evidence = (
        EvidenceClassification.CALCULATED
        if all(
            p.evidence in (EvidenceClassification.MEASURED, EvidenceClassification.CALCULATED)
            for p in (three_phase.phase_a, three_phase.phase_b, three_phase.phase_c)
        )
        else EvidenceClassification.MODELED
    )
    quality = (
        MeasurementQuality.SUSPECT
        if any(
            p.quality == MeasurementQuality.SUSPECT
            for p in (three_phase.phase_a, three_phase.phase_b, three_phase.phase_c)
        )
        else MeasurementQuality.GOOD
    )

    cp_0 = ComplexPhasor.from_complex(x0, unit=unit)
    cp_1 = ComplexPhasor.from_complex(x1, unit=unit)
    cp_2 = ComplexPhasor.from_complex(x2, unit=unit)

    meas_mag_0 = Measurement(
        value=mag_0,
        unit=unit,
        evidence=evidence,
        quality=quality,
        timestamp=ts,
        metadata={"sequence": "ZERO", "component": "X0"},
    )
    meas_mag_1 = Measurement(
        value=mag_1,
        unit=unit,
        evidence=evidence,
        quality=quality,
        timestamp=ts,
        metadata={"sequence": "POSITIVE", "component": "X1"},
    )
    meas_mag_2 = Measurement(
        value=mag_2,
        unit=unit,
        evidence=evidence,
        quality=quality,
        timestamp=ts,
        metadata={"sequence": "NEGATIVE", "component": "X2"},
    )

    # 7. Sequence Ratios (Negative-sequence ratio VUF / CUF, Zero-sequence ratio)
    vuf_cuf_meas: Optional[Measurement[float]] = None
    v0_c0_meas: Optional[Measurement[float]] = None

    if mag_1 <= NEAR_ZERO_SEQUENCE_THRESHOLD:
        issues.append(
            ProcessingIssue(
                stage=stage_name,
                severity=IssueSeverity.WARNING,
                code=ERR_DEGENERATE_POSITIVE_SEQUENCE,
                message=(
                    f"Positive-sequence component magnitude ({mag_1:.6e} {unit}) is below numerical "
                    f"safety threshold ({NEAR_ZERO_SEQUENCE_THRESHOLD}). Sequence ratios cannot be calculated. "
                    f"Division by zero avoided."
                ),
                field_name=f"{quantity_type.lower()}_positive_sequence",
                timestamp=ts,
            )
        )
    else:
        neg_ratio = (mag_2 / mag_1) * 100.0
        zero_ratio = (mag_0 / mag_1) * 100.0

        vuf_cuf_meas = Measurement(
            value=neg_ratio,
            unit="percent",
            evidence=evidence,
            quality=quality,
            timestamp=ts,
            metadata={
                "formula": "(|X2| / |X1|) * 100",
                "standard": "IEC 61000-4-30 / IEC 60076",
                "metric_name": "VUF" if quantity_type == "VOLTAGE" else "CUF",
                "denominator": "POSITIVE_SEQUENCE_MAGNITUDE",
            },
        )
        v0_c0_meas = Measurement(
            value=zero_ratio,
            unit="percent",
            evidence=evidence,
            quality=quality,
            timestamp=ts,
            metadata={
                "formula": "(|X0| / |X1|) * 100",
                "metric_name": "V0UF" if quantity_type == "VOLTAGE" else "C0UF",
                "denominator": "POSITIVE_SEQUENCE_MAGNITUDE",
            },
        )

    # 8. Neutral current calculation for 4-wire current systems
    neutral_cp: Optional[ComplexPhasor] = None
    neutral_mag_meas: Optional[Measurement[float]] = None
    if quantity_type == "CURRENT":
        # In = -(Ia + Ib + Ic) = -3 * I0
        in_complex = -3.0 * x0
        neutral_cp = ComplexPhasor.from_complex(in_complex, unit=unit)
        neutral_mag_meas = Measurement(
            value=abs(in_complex),
            unit=unit,
            evidence=evidence,
            quality=quality,
            timestamp=ts,
            metadata={
                "formula": "-3 * I0",
                "definition": "Calculated 4-wire neutral return current phasor magnitude",
            },
        )

    return (
        SymmetricalComponentsResult(
            quantity_type=quantity_type,
            zero_sequence=cp_0,
            positive_sequence=cp_1,
            negative_sequence=cp_2,
            zero_sequence_magnitude=meas_mag_0,
            positive_sequence_magnitude=meas_mag_1,
            negative_sequence_magnitude=meas_mag_2,
            negative_sequence_ratio_percent=vuf_cuf_meas,
            zero_sequence_ratio_percent=v0_c0_meas,
            neutral_current=neutral_cp,
            neutral_current_magnitude=neutral_mag_meas,
            phase_sequence=seq,
            reconstruction_max_error=max_recon_err,
            is_valid=True,
            evidence=evidence,
        ),
        issues,
    )


def calculate_transformer_derating(
    current_imbalance: Optional[PhaseMagnitudeImbalance],
    current_symmetrical: Optional[SymmetricalComponentsResult],
    voltage_imbalance: Optional[PhaseMagnitudeImbalance],
    voltage_symmetrical: Optional[SymmetricalComponentsResult],
    asset_spec: TransformerAssetSpec,
    operational_limits: Optional[OperationalLimits] = None,
    derating_config: Optional[DeratingConfiguration] = None,
    timestamp: Optional[datetime] = None,
    stage_name: str = "derating_analysis",
) -> Tuple[Optional[DeratingAssessmentResult], List[ProcessingIssue]]:
    """
    Evidence-grounded transformer derating calculation under unbalanced loading.
    Evaluates:
    1. Maximum phase current capacity derating method (deterministic conductor capacity limit).
    2. Loss-based negative-sequence method (requires verified factory test loss ratios).
    3. Operational limit violations for voltage and current unbalance.
    Explicitly refuses to apply NEMA MG-1 induction motor derating to static transformers.
    """
    issues: List[ProcessingIssue] = []
    ts = timestamp or datetime.now(timezone.utc)
    config = derating_config or DeratingConfiguration()
    recs: List[str] = []

    # 1. Operational limit checks
    limits = operational_limits or asset_spec.operational_limits
    if limits is not None:
        # Check voltage unbalance limit
        v_unbalance_pct = None
        if voltage_symmetrical and voltage_symmetrical.negative_sequence_ratio_percent:
            v_unbalance_pct = voltage_symmetrical.negative_sequence_ratio_percent.value
        elif voltage_imbalance and voltage_imbalance.max_deviation_percent:
            v_unbalance_pct = voltage_imbalance.max_deviation_percent.value

        if v_unbalance_pct is not None and v_unbalance_pct > limits.max_voltage_unbalance_percent:
            issues.append(
                ProcessingIssue(
                    stage=stage_name,
                    severity=IssueSeverity.WARNING,
                    code=WARN_VOLTAGE_UNBALANCE_EXCEEDS_LIMIT,
                    message=(
                        f"Voltage unbalance ({v_unbalance_pct:.2f}%) exceeds operational limit "
                        f"({limits.max_voltage_unbalance_percent:.2f}%)."
                    ),
                    field_name="voltage_unbalance",
                    timestamp=ts,
                )
            )
            recs.append(
                f"Voltage unbalance ({v_unbalance_pct:.2f}%) exceeds operational threshold ({limits.max_voltage_unbalance_percent:.2f}%). Investigate upstream phase balance."
            )

        # Check current unbalance limit
        c_unbalance_pct = None
        if current_symmetrical and current_symmetrical.negative_sequence_ratio_percent:
            c_unbalance_pct = current_symmetrical.negative_sequence_ratio_percent.value
        elif current_imbalance and current_imbalance.max_deviation_percent:
            c_unbalance_pct = current_imbalance.max_deviation_percent.value

        if c_unbalance_pct is not None and c_unbalance_pct > limits.max_current_unbalance_percent:
            issues.append(
                ProcessingIssue(
                    stage=stage_name,
                    severity=IssueSeverity.WARNING,
                    code=WARN_CURRENT_UNBALANCE_EXCEEDS_LIMIT,
                    message=(
                        f"Current unbalance ({c_unbalance_pct:.2f}%) exceeds operational limit "
                        f"({limits.max_current_unbalance_percent:.2f}%)."
                    ),
                    field_name="current_unbalance",
                    timestamp=ts,
                )
            )
            recs.append(
                f"Current unbalance ({c_unbalance_pct:.2f}%) exceeds operational threshold ({limits.max_current_unbalance_percent:.2f}%). Redistribute single-phase feeder loads."
            )

    # 2. Method evaluation
    method = config.method

    if method == DeratingMethod.MAX_PHASE_CURRENT_CAPACITY:
        if current_imbalance is None or not current_imbalance.is_valid:
            issues.append(
                ProcessingIssue(
                    stage=stage_name,
                    severity=IssueSeverity.WARNING,
                    code=WARN_DERATING_METHOD_UNAVAILABLE,
                    message="Current magnitude imbalance is unavailable; cannot compute maximum-phase derating.",
                    field_name="derating_factor",
                    timestamp=ts,
                )
            )
            return (
                DeratingAssessmentResult(
                    derating_factor_pu=None,
                    method_applied=DeratingMethod.MAX_PHASE_CURRENT_CAPACITY,
                    is_derated=False,
                    status="UNKNOWN",
                    applicability_notes="Conductor thermal limit method requires valid three-phase current telemetry.",
                    limitations="Missing current measurements prevent evaluating phase conductor loading.",
                    engineering_recommendations=recs,
                ),
                issues,
            )

        mean_i = current_imbalance.mean_magnitude.value
        max_dev_i = current_imbalance.max_absolute_deviation.value

        if mean_i <= 0.0:
            derate_pu = 1.0
            is_derated = False
        else:
            # Maximum phase current: I_max = mean_i + max_dev_i
            # Derating factor = mean_i / I_max = 1 / (1 + max_dev_i / mean_i)
            i_max = mean_i + max_dev_i
            derate_pu = min(1.0, mean_i / i_max) if i_max > 0.0 else 1.0
            is_derated = derate_pu < 0.999

        meas_derate = Measurement(
            value=derate_pu,
            unit="pu",
            evidence=EvidenceClassification.CALCULATED,
            quality=current_imbalance.mean_magnitude.quality,
            timestamp=ts,
            metadata={
                "method": "MAX_PHASE_CURRENT_CAPACITY",
                "formula": "mean_current / max_phase_current",
                "rationale": "Prevents individual phase conductor thermal limit exceedance under asymmetrical load.",
            },
        )

        if is_derated:
            recs.append(
                f"Derate transformer nameplate capacity to {derate_pu * 100:.1f}% ({derate_pu:.3f} pu) to avoid exceeding single-phase conductor thermal ratings."
            )

        return (
            DeratingAssessmentResult(
                derating_factor_pu=meas_derate,
                method_applied=DeratingMethod.MAX_PHASE_CURRENT_CAPACITY,
                is_derated=is_derated,
                status="CALCULATED",
                applicability_notes=(
                    "Applicable to distribution transformers operating under asymmetrical single-phase load. "
                    "Constrains total three-phase throughput so the most heavily loaded phase does not exceed rated current."
                ),
                limitations="Evaluates fundamental-frequency phase current magnitude only; does not model localized stray flux or tank heating.",
                engineering_recommendations=recs,
            ),
            issues,
        )

    elif method == DeratingMethod.LOSS_BASED_NEGATIVE_SEQUENCE:
        # Requires verified asset test parameters (loss ratio R and eddy-current loss factor PEC)
        r = config.loss_ratio_r
        pec = config.eddy_loss_factor_pec

        if r is None or pec is None:
            issues.append(
                ProcessingIssue(
                    stage=stage_name,
                    severity=IssueSeverity.WARNING,
                    code=WARN_UNVERIFIED_DERATING_PARAMETERS,
                    message=(
                        "Loss-based negative-sequence derating requires verified factory test parameters: "
                        "loss ratio (R) and eddy current loss factor (PEC). Parameters unavailable; returning UNKNOWN."
                    ),
                    field_name="derating_parameters",
                    timestamp=ts,
                )
            )
            recs.append("Obtain factory test report with load-loss ratio and eddy-loss factor to compute loss-based derating.")
            return (
                DeratingAssessmentResult(
                    derating_factor_pu=None,
                    method_applied=DeratingMethod.LOSS_BASED_NEGATIVE_SEQUENCE,
                    is_derated=False,
                    status="UNVERIFIED",
                    applicability_notes="Requires verified factory test report parameters.",
                    limitations="Parameters unverified; standard practice prohibits speculative loss coefficients.",
                    engineering_recommendations=recs,
                ),
                issues,
            )

        # If parameters present and symmetrical current available:
        if current_symmetrical and current_symmetrical.negative_sequence_ratio_percent:
            cuf = current_symmetrical.negative_sequence_ratio_percent.value / 100.0
            # Additional loss factor: 1 + pec * cuf^2
            additional_loss_factor = 1.0 + pec * (cuf ** 2)
            derate_pu = min(1.0, math.sqrt((1.0 + r) / (1.0 + r * additional_loss_factor)))
            is_derated = derate_pu < 0.999

            meas_derate = Measurement(
                value=derate_pu,
                unit="pu",
                evidence=EvidenceClassification.CALCULATED,
                quality=current_symmetrical.negative_sequence_ratio_percent.quality,
                timestamp=ts,
                metadata={
                    "method": "LOSS_BASED_NEGATIVE_SEQUENCE",
                    "loss_ratio_r": r,
                    "eddy_loss_factor_pec": pec,
                    "cuf_pu": cuf,
                },
            )
            return (
                DeratingAssessmentResult(
                    derating_factor_pu=meas_derate,
                    method_applied=DeratingMethod.LOSS_BASED_NEGATIVE_SEQUENCE,
                    is_derated=is_derated,
                    status="CALCULATED",
                    applicability_notes="Derived from verified factory loss ratio and negative-sequence eddy losses.",
                    limitations="Assumes uniform loss distribution across winding coils.",
                    engineering_recommendations=recs,
                ),
                issues,
            )
        else:
            issues.append(
                ProcessingIssue(
                    stage=stage_name,
                    severity=IssueSeverity.WARNING,
                    code=WARN_DERATING_METHOD_UNAVAILABLE,
                    message="Current symmetrical components unavailable for loss-based derating.",
                    field_name="current_symmetrical",
                    timestamp=ts,
                )
            )
            return (
                DeratingAssessmentResult(
                    derating_factor_pu=None,
                    method_applied=DeratingMethod.LOSS_BASED_NEGATIVE_SEQUENCE,
                    is_derated=False,
                    status="UNKNOWN",
                    applicability_notes="Requires current symmetrical components.",
                    limitations="Missing current phasors.",
                    engineering_recommendations=recs,
                ),
                issues,
            )

    else:
        # Unsupported or unconfigured method
        issues.append(
            ProcessingIssue(
                stage=stage_name,
                severity=IssueSeverity.INFO,
                code=WARN_DERATING_METHOD_UNAVAILABLE,
                message=f"Derating method '{method}' is not configured or unsupported.",
                field_name="derating_method",
                timestamp=ts,
            )
        )
        return (
            DeratingAssessmentResult(
                derating_factor_pu=None,
                method_applied=method,
                is_derated=False,
                status="UNKNOWN",
                applicability_notes="No applicable derating method configured.",
                limitations="Generic or unverified derating curves are excluded by GridPulse safety policy.",
                engineering_recommendations=recs,
            ),
            issues,
        )
