"""
GridPulse — Deterministic Electrical Engineering Calculations
Part of scientific.features.

Closed-form electrical formulations strictly adhering to Phase 2 Step 3 principles:
1. Apparent power from active and reactive power: S = sqrt(P² + Q²)
2. GridPulse Signed Power Factor: PF = P / S  (P > 0: Import/Consumption, P < 0: Export/Generation, S >= 0)
3. Three-phase average phase RMS voltage: V_avg = (V_A + V_B + V_C) / 3
4. Three-phase average phase RMS current: I_avg = (I_A + I_B + I_C) / 3

Scientific Invariants:
- Output evidence is strictly CALCULATED.
- No Large Language Model (LLM) participation.
- Zero fabrication: missing telemetry yields insufficient telemetry without assumptions.
- Unit-independent numerical safety: near-zero threshold is evaluated in canonical units.
- No silent clamping of out-of-domain results.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple

from scientific.contracts.enums import EvidenceClassification, IssueSeverity, MeasurementQuality
from scientific.contracts.issues import ProcessingIssue
from scientific.contracts.measurement import Measurement


# Canonical near-zero threshold for apparent power, defined in canonical kVA:
# 1e-6 kVA = 0.001 VA = 1 mVA.
# Any apparent power is converted to its canonical kVA equivalent before comparison.
NEAR_ZERO_APPARENT_POWER_KVA: float = 1e-6

# Unit conversion factors to canonical base (kW, kVAR, kVA)
POWER_SCALE_TO_CANONICAL: Dict[str, float] = {
    # Active
    "w": 1e-3,
    "kw": 1.0,
    "mw": 1e3,
    # Reactive
    "var": 1e-3,
    "kvar": 1.0,
    "mvar": 1e3,
    # Apparent
    "va": 1e-3,
    "kva": 1.0,
    "mva": 1e3,
}

# Derived apparent power unit matching input prefix
POWER_PREFIX_TO_APPARENT_UNIT: Dict[str, str] = {
    "w": "VA",
    "kw": "kVA",
    "mw": "MVA",
}


def normalize_power_to_canonical_kva(val: float, unit: str) -> Optional[float]:
    """Converts a power value in W/kW/MW/VAR/kVAR/MVAR/VA/kVA/MVA to canonical kVA/kW/kVAR."""
    scale = POWER_SCALE_TO_CANONICAL.get(unit.strip().lower())
    if scale is None:
        return None
    return val * scale


def calculate_apparent_power(
    p: Optional[Measurement[float]],
    q: Optional[Measurement[float]],
    asset_id: str,
    timestamp: datetime,
) -> Tuple[Optional[Measurement[float]], List[ProcessingIssue]]:
    """
    Computes apparent power from active and reactive power:
    S = sqrt(P² + Q²)

    Units:
    kW + kVAR -> kVA
    W + VAR -> VA
    MW + MVAR -> MVA

    Output evidence: strictly CALCULATED.
    """
    issues: List[ProcessingIssue] = []

    # 1. Missing Data Check
    if p is None or p.value is None:
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.WARNING,
                code="ERR_INSUFFICIENT_TELEMETRY",
                message="Cannot calculate apparent power: active power (P) is missing. Zero is not assumed.",
                field_name="active_power",
                timestamp=timestamp,
            )
        )
        return None, issues

    if q is None or q.value is None:
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.WARNING,
                code="ERR_INSUFFICIENT_TELEMETRY",
                message="Cannot calculate apparent power: reactive power (Q) is missing. Zero is not assumed.",
                field_name="reactive_power",
                timestamp=timestamp,
            )
        )
        return None, issues

    # 2. Non-Finite Checks
    if not math.isfinite(p.value) or not math.isfinite(q.value):
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.CRITICAL,
                code="ERR_NON_FINITE_INPUT",
                message=f"Non-finite input encountered: P={p.value}, Q={q.value}.",
                field_name="apparent_power",
                timestamp=timestamp,
            )
        )
        return None, issues

    # 3. Unit Compatibility Verification
    p_unit = p.unit.strip().lower()
    q_unit = q.unit.strip().lower()

    # Determine output unit
    out_unit = "kVA"
    if p_unit == "kw" and q_unit == "kvar":
        out_unit = "kVA"
        p_val = p.value
        q_val = q.value
    elif p_unit == "w" and q_unit == "var":
        out_unit = "VA"
        p_val = p.value
        q_val = q.value
    elif p_unit == "mw" and q_unit == "mvar":
        out_unit = "MVA"
        p_val = p.value
        q_val = q.value
    else:
        # Cross-prefix normalization to canonical kW & kVAR -> kVA
        p_canon = normalize_power_to_canonical_kva(p.value, p.unit)
        q_canon = normalize_power_to_canonical_kva(q.value, q.unit)
        if p_canon is None or q_canon is None:
            issues.append(
                ProcessingIssue(
                    stage="features",
                    severity=IssueSeverity.CRITICAL,
                    code="ERR_INCOMPATIBLE_UNITS",
                    message=f"Incompatible power units for S calculation: P unit='{p.unit}', Q unit='{q.unit}'.",
                    field_name="apparent_power",
                    timestamp=timestamp,
                )
            )
            return None, issues
        p_val = p_canon
        q_val = q_canon
        out_unit = "kVA"

    # 4. Deterministic Calculation: S = sqrt(P² + Q²)
    s_val = math.sqrt(p_val * p_val + q_val * q_val)

    # Propagate quality: SUSPECT if either input is SUSPECT, else GOOD
    quality = MeasurementQuality.GOOD
    if p.quality == MeasurementQuality.SUSPECT or q.quality == MeasurementQuality.SUSPECT:
        quality = MeasurementQuality.SUSPECT

    provenance_meta = {
        "formula_id": "APPARENT_POWER_FROM_P_Q",
        "equation": "sqrt(P^2 + Q^2)",
        "inputs": {
            "p": {"value": p.value, "unit": p.unit, "evidence": p.evidence.value},
            "q": {"value": q.value, "unit": q.unit, "evidence": q.evidence.value},
        },
        "asset_id": asset_id,
        "calculation_timestamp": timestamp.isoformat(),
    }

    measurement = Measurement(
        value=s_val,
        unit=out_unit,
        evidence=EvidenceClassification.CALCULATED,
        quality=quality,
        timestamp=timestamp,
        metadata=provenance_meta,
    )

    return measurement, issues


def calculate_power_factor(
    p: Optional[Measurement[float]],
    s: Optional[Measurement[float]],
    q: Optional[Measurement[float]] = None,
    asset_id: str = "",
    timestamp: Optional[datetime] = None,
) -> Tuple[Optional[Measurement[float]], List[ProcessingIssue]]:
    """
    Computes GridPulse Signed Power Factor from active and apparent power:
    PF = P / S

    GridPulse Signed Convention:
    - P > 0: Import / Consumption -> PF > 0
    - P < 0: Export / Generation  -> PF < 0
    - S >= 0
    - Domain: PF ∈ [-1.0, 1.0]

    Unit-independent numerical safety:
    - S is normalized to canonical kVA before comparing against NEAR_ZERO_APPARENT_POWER_KVA.

    No silent clamping:
    - If calculated |PF| > 1.0, domain validation fails with a structured issue.
    """
    issues: List[ProcessingIssue] = []
    calc_ts = timestamp or (p.timestamp if p else datetime.now(timezone.utc))

    # 1. Missing Data Check
    if p is None or p.value is None:
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.WARNING,
                code="ERR_INSUFFICIENT_TELEMETRY",
                message="Cannot calculate power factor: active power (P) is missing. PF is not assumed to be 1.0.",
                field_name="power_factor",
                timestamp=calc_ts,
            )
        )
        return None, issues

    if s is None or s.value is None:
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.WARNING,
                code="ERR_INSUFFICIENT_TELEMETRY",
                message="Cannot calculate power factor: apparent power (S) is missing. Zero is not assumed.",
                field_name="power_factor",
                timestamp=calc_ts,
            )
        )
        return None, issues

    # 2. Non-Finite Check
    if not math.isfinite(p.value) or not math.isfinite(s.value):
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.CRITICAL,
                code="ERR_NON_FINITE_INPUT",
                message=f"Non-finite input encountered: P={p.value}, S={s.value}.",
                field_name="power_factor",
                timestamp=calc_ts,
            )
        )
        return None, issues

    # 3. Unit-Independent Numerical Safety Check on S
    # Normalize S to canonical kVA for unit-independent near-zero check
    s_canon = normalize_power_to_canonical_kva(s.value, s.unit)
    if s_canon is None:
        # Fallback if unit unrecognized
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.CRITICAL,
                code="ERR_INCOMPATIBLE_UNITS",
                message=f"Unrecognized apparent power unit '{s.unit}' for power factor calculation.",
                field_name="power_factor",
                timestamp=calc_ts,
            )
        )
        return None, issues

    if s_canon <= NEAR_ZERO_APPARENT_POWER_KVA:
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.WARNING,
                code="WARN_NEAR_ZERO_APPARENT_POWER",
                message=(
                    f"Cannot compute power factor: apparent power S={s.value} {s.unit} "
                    f"({s_canon:.9f} kVA canonical) is below numerical safety threshold "
                    f"{NEAR_ZERO_APPARENT_POWER_KVA} kVA (1 mVA). Division by zero avoided."
                ),
                field_name="power_factor",
                timestamp=calc_ts,
            )
        )
        return None, issues

    # 4. Normalize P and S to identical units (canonical kW and kVA)
    p_canon = normalize_power_to_canonical_kva(p.value, p.unit)
    if p_canon is None:
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.CRITICAL,
                code="ERR_INCOMPATIBLE_UNITS",
                message=f"Unrecognized active power unit '{p.unit}' for power factor calculation.",
                field_name="power_factor",
                timestamp=calc_ts,
            )
        )
        return None, issues

    # 5. Deterministic Calculation: PF = P / S
    raw_pf = p_canon / s_canon

    # 6. Domain Validation (No Silent Clamping!)
    # Floating-point tolerance for exact unity comparison:
    # A difference within 1e-12 is accepted as mathematically 1.0 / -1.0
    if abs(raw_pf) > 1.0 + 1e-12:
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.CRITICAL,
                code="ERR_CALCULATED_PF_DOMAIN_VIOLATION",
                message=(
                    f"Calculated power factor {raw_pf:.6f} violates physical domain [-1.0, 1.0] "
                    f"(P={p.value} {p.unit}, S={s.value} {s.unit}). Silent clamping is prohibited; calculation rejected."
                ),
                field_name="power_factor",
                timestamp=calc_ts,
            )
        )
        return None, issues

    # If within floating-point tolerance of unity (e.g. 1.0000000000001), exact-clamp to 1.0
    pf_val = max(min(raw_pf, 1.0), -1.0)

    # Quality propagation
    quality = MeasurementQuality.GOOD
    if p.quality == MeasurementQuality.SUSPECT or s.quality == MeasurementQuality.SUSPECT:
        quality = MeasurementQuality.SUSPECT

    provenance_meta = {
        "formula_id": "POWER_FACTOR_FROM_P_S",
        "equation": "P / S",
        "convention": "GRIDPULSE_SIGNED_PF_P_DIV_S",
        "inputs": {
            "p": {"value": p.value, "unit": p.unit, "evidence": p.evidence.value},
            "s": {"value": s.value, "unit": s.unit, "evidence": s.evidence.value},
        },
        "asset_id": asset_id,
        "calculation_timestamp": calc_ts.isoformat(),
    }
    if q and q.value is not None:
        provenance_meta["reactive_quadrant"] = "INDUCTIVE_LAGGING" if q.value >= 0 else "CAPACITIVE_LEADING"

    measurement = Measurement(
        value=pf_val,
        unit="ratio",
        evidence=EvidenceClassification.CALCULATED,
        quality=quality,
        timestamp=calc_ts,
        metadata=provenance_meta,
    )

    return measurement, issues


def calculate_three_phase_average_voltage(
    va: Optional[Measurement[float]],
    vb: Optional[Measurement[float]],
    vc: Optional[Measurement[float]],
    asset_id: str,
    timestamp: datetime,
) -> Tuple[Optional[Measurement[float]], List[ProcessingIssue]]:
    """
    Computes three-phase average phase RMS voltage:
    V_avg = (V_A + V_B + V_C) / 3

    Explicitly identified as: average phase RMS voltage.
    Not line-to-line, not total voltage, not phase balance.
    All three phases must be present; missing phases are never invented.
    """
    issues: List[ProcessingIssue] = []

    # Check that all three phases exist
    missing_phases = []
    if va is None or va.value is None:
        missing_phases.append("Phase A")
    if vb is None or vb.value is None:
        missing_phases.append("Phase B")
    if vc is None or vc.value is None:
        missing_phases.append("Phase C")

    if missing_phases:
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.WARNING,
                code="ERR_INSUFFICIENT_TELEMETRY",
                message=(
                    f"Cannot calculate three-phase average voltage: missing telemetry for {', '.join(missing_phases)}. "
                    f"Missing phase voltages are never fabricated."
                ),
                field_name="average_phase_voltage",
                timestamp=timestamp,
            )
        )
        return None, issues

    # Non-finite check
    if not (math.isfinite(va.value) and math.isfinite(vb.value) and math.isfinite(vc.value)):
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.CRITICAL,
                code="ERR_NON_FINITE_INPUT",
                message="Non-finite input encountered in phase voltages.",
                field_name="average_phase_voltage",
                timestamp=timestamp,
            )
        )
        return None, issues

    # Unit consistency check
    if not (va.unit == vb.unit == vc.unit):
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.CRITICAL,
                code="ERR_INCOMPATIBLE_UNITS",
                message=f"Mismatched phase voltage units: VA='{va.unit}', VB='{vb.unit}', VC='{vc.unit}'.",
                field_name="average_phase_voltage",
                timestamp=timestamp,
            )
        )
        return None, issues

    v_avg = (va.value + vb.value + vc.value) / 3.0

    quality = MeasurementQuality.GOOD
    if any(m.quality == MeasurementQuality.SUSPECT for m in (va, vb, vc)):
        quality = MeasurementQuality.SUSPECT

    provenance_meta = {
        "formula_id": "AVERAGE_PHASE_VOLTAGE_3P",
        "equation": "(V_A + V_B + V_C) / 3",
        "definition": "Average Phase RMS Voltage",
        "inputs": {
            "v_a": {"value": va.value, "unit": va.unit, "evidence": va.evidence.value},
            "v_b": {"value": vb.value, "unit": vb.unit, "evidence": vb.evidence.value},
            "v_c": {"value": vc.value, "unit": vc.unit, "evidence": vc.evidence.value},
        },
        "asset_id": asset_id,
        "calculation_timestamp": timestamp.isoformat(),
    }

    measurement = Measurement(
        value=v_avg,
        unit=va.unit,
        evidence=EvidenceClassification.CALCULATED,
        quality=quality,
        timestamp=timestamp,
        metadata=provenance_meta,
    )

    return measurement, issues


def calculate_three_phase_average_current(
    ia: Optional[Measurement[float]],
    ib: Optional[Measurement[float]],
    ic: Optional[Measurement[float]],
    asset_id: str,
    timestamp: datetime,
) -> Tuple[Optional[Measurement[float]], List[ProcessingIssue]]:
    """
    Computes three-phase average phase RMS current:
    I_avg = (I_A + I_B + I_C) / 3

    Explicitly identified as: average phase RMS current.
    Not total current, not phase balance.
    All three phases must be present; missing phases are never invented.
    """
    issues: List[ProcessingIssue] = []

    # Check that all three phases exist
    missing_phases = []
    if ia is None or ia.value is None:
        missing_phases.append("Phase A")
    if ib is None or ib.value is None:
        missing_phases.append("Phase B")
    if ic is None or ic.value is None:
        missing_phases.append("Phase C")

    if missing_phases:
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.WARNING,
                code="ERR_INSUFFICIENT_TELEMETRY",
                message=(
                    f"Cannot calculate three-phase average current: missing telemetry for {', '.join(missing_phases)}. "
                    f"Missing phase currents are never fabricated."
                ),
                field_name="average_phase_current",
                timestamp=timestamp,
            )
        )
        return None, issues

    # Non-finite check
    if not (math.isfinite(ia.value) and math.isfinite(ib.value) and math.isfinite(ic.value)):
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.CRITICAL,
                code="ERR_NON_FINITE_INPUT",
                message="Non-finite input encountered in phase currents.",
                field_name="average_phase_current",
                timestamp=timestamp,
            )
        )
        return None, issues

    # Unit consistency check
    if not (ia.unit == ib.unit == ic.unit):
        issues.append(
            ProcessingIssue(
                stage="features",
                severity=IssueSeverity.CRITICAL,
                code="ERR_INCOMPATIBLE_UNITS",
                message=f"Mismatched phase current units: IA='{ia.unit}', IB='{ib.unit}', IC='{ic.unit}'.",
                field_name="average_phase_current",
                timestamp=timestamp,
            )
        )
        return None, issues

    i_avg = (ia.value + ib.value + ic.value) / 3.0

    quality = MeasurementQuality.GOOD
    if any(m.quality == MeasurementQuality.SUSPECT for m in (ia, ib, ic)):
        quality = MeasurementQuality.SUSPECT

    provenance_meta = {
        "formula_id": "AVERAGE_PHASE_CURRENT_3P",
        "equation": "(I_A + I_B + I_C) / 3",
        "definition": "Average Phase RMS Current",
        "inputs": {
            "i_a": {"value": ia.value, "unit": ia.unit, "evidence": ia.evidence.value},
            "i_b": {"value": ib.value, "unit": ib.unit, "evidence": ib.evidence.value},
            "i_c": {"value": ic.value, "unit": ic.unit, "evidence": ic.evidence.value},
        },
        "asset_id": asset_id,
        "calculation_timestamp": timestamp.isoformat(),
    }

    measurement = Measurement(
        value=i_avg,
        unit=ia.unit,
        evidence=EvidenceClassification.CALCULATED,
        quality=quality,
        timestamp=timestamp,
        metadata=provenance_meta,
    )

    return measurement, issues
