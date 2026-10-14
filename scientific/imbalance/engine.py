"""
GridPulse — Phase Imbalance & Symmetrical Components Calculation Engine
Coordinates deterministic three-phase magnitude imbalance, Fortescue symmetrical components,
neutral current evaluation, and evidence-grounded transformer derating.
Part of Phase 2 Step 6.
"""

from typing import Any, Dict, List, Optional, Tuple

from scientific.contracts.asset import OperationalLimits, TransformerAssetSpec
from scientific.contracts.enums import IssueSeverity
from scientific.contracts.issues import ERR_MISSING_TIMESTAMP, ProcessingIssue
from scientific.contracts.measurement import Measurement
from scientific.contracts.results import PhaseImbalanceResult
from scientific.imbalance.calculations import (
    calculate_phase_magnitude_imbalance,
    calculate_symmetrical_components,
    calculate_transformer_derating,
)
from scientific.imbalance.contracts import (
    DeratingAssessmentResult,
    PhaseImbalanceInput,
    PhaseMagnitudeImbalance,
    SymmetricalComponentsResult,
    ThreePhaseQuantity,
)

STAGE_NAME: str = "phase_imbalance_analysis"


class PhaseImbalanceEngine:
    """
    Deterministic calculation engine for phase unbalance and symmetrical components.
    Guarantees:
    - Zero fabrication of missing phase telemetry or phase angles.
    - Symmetrical components require valid complex phasors.
    - Magnitude-only readings support magnitude-based metrics (PVUR, CMUR) but not sequence components.
    - Derating is evidence-grounded and rejects unverified motor curves for transformers.
    """

    def __init__(
        self,
        asset_spec: Optional[TransformerAssetSpec] = None,
        operational_limits: Optional[OperationalLimits] = None,
    ) -> None:
        self.asset_spec = asset_spec
        self.operational_limits = operational_limits

    def compute_imbalance(
        self,
        input_data: PhaseImbalanceInput,
    ) -> Tuple[PhaseImbalanceResult, List[ProcessingIssue]]:
        """
        Executes deterministic phase imbalance and symmetrical component calculations.
        """
        issues: List[ProcessingIssue] = []
        eff_spec = input_data.asset_spec or self.asset_spec
        eff_limits = input_data.operational_limits or self.operational_limits or (eff_spec.operational_limits if eff_spec else None)

        # 1. Resolve ThreePhaseQuantity for Voltage
        v_three_phase = input_data.voltage_three_phase
        if v_three_phase is None and input_data.features is not None:
            feat = input_data.features
            if feat.v_a_rms and feat.v_b_rms and feat.v_c_rms:
                ts = feat.v_a_rms.timestamp
                asset_id = eff_spec.asset_id if eff_spec else ""
                v_three_phase = ThreePhaseQuantity.from_measurements(
                    va=feat.v_a_rms,
                    vb=feat.v_b_rms,
                    vc=feat.v_c_rms,
                    asset_id=asset_id,
                    timestamp=ts,
                )

        # 2. Resolve ThreePhaseQuantity for Current
        i_three_phase = input_data.current_three_phase
        if i_three_phase is None and input_data.features is not None:
            feat = input_data.features
            if feat.i_a_rms and feat.i_b_rms and feat.i_c_rms:
                ts = feat.i_a_rms.timestamp
                asset_id = eff_spec.asset_id if eff_spec else ""
                i_three_phase = ThreePhaseQuantity.from_measurements(
                    va=feat.i_a_rms,
                    vb=feat.i_b_rms,
                    vc=feat.i_c_rms,
                    asset_id=asset_id,
                    timestamp=ts,
                )

        # Establish effective timestamp and asset_id deterministically (F-06: no wall-clock fallback)
        calc_ts = (
            v_three_phase.timestamp
            if v_three_phase and v_three_phase.timestamp
            else (
                i_three_phase.timestamp
                if i_three_phase and i_three_phase.timestamp
                else (
                    input_data.loading.loading_ratio_pu.timestamp
                    if input_data.loading and input_data.loading.loading_ratio_pu and input_data.loading.loading_ratio_pu.timestamp
                    else None
                )
            )
        )
        if calc_ts is None:
            issues.append(
                ProcessingIssue(
                    stage=STAGE_NAME,
                    severity=IssueSeverity.CRITICAL,
                    code=ERR_MISSING_TIMESTAMP,
                    message="No valid deterministic timestamp found in input data. Telemetry timestamps cannot be manufactured from wall-clock.",
                )
            )
            return (
                PhaseImbalanceResult(
                    is_computed=False,
                    issues=issues,
                    calculation_provenance={"pipeline_stage": STAGE_NAME, "status": "REJECTED_MISSING_TIMESTAMP"},
                ),
                issues,
            )

        asset_id = eff_spec.asset_id if eff_spec else ""

        # 3. Voltage Magnitude Imbalance
        v_mag_imbalance: Optional[PhaseMagnitudeImbalance] = None
        if v_three_phase is not None:
            v_mag_imbalance, v_mag_issues = calculate_phase_magnitude_imbalance(
                three_phase=v_three_phase,
                quantity_type="VOLTAGE",
                stage_name=STAGE_NAME,
            )
            issues.extend(v_mag_issues)

        # 4. Current Magnitude Imbalance
        i_mag_imbalance: Optional[PhaseMagnitudeImbalance] = None
        if i_three_phase is not None:
            i_mag_imbalance, i_mag_issues = calculate_phase_magnitude_imbalance(
                three_phase=i_three_phase,
                quantity_type="CURRENT",
                stage_name=STAGE_NAME,
            )
            issues.extend(i_mag_issues)

        # 5. Voltage Symmetrical Components (only if complex phasors exist)
        v_symmetrical: Optional[SymmetricalComponentsResult] = None
        if v_three_phase is not None:
            v_symmetrical, v_sym_issues = calculate_symmetrical_components(
                three_phase=v_three_phase,
                quantity_type="VOLTAGE",
                stage_name=STAGE_NAME,
            )
            issues.extend(v_sym_issues)

        # 6. Current Symmetrical Components (only if complex phasors exist)
        i_symmetrical: Optional[SymmetricalComponentsResult] = None
        if i_three_phase is not None:
            i_symmetrical, i_sym_issues = calculate_symmetrical_components(
                three_phase=i_three_phase,
                quantity_type="CURRENT",
                stage_name=STAGE_NAME,
            )
            issues.extend(i_sym_issues)

        # 7. Derating Assessment (F-01: passes current_three_phase)
        derating_res: Optional[DeratingAssessmentResult] = None
        if eff_spec is not None:
            derating_res, derating_issues = calculate_transformer_derating(
                current_imbalance=i_mag_imbalance,
                current_symmetrical=i_symmetrical,
                voltage_imbalance=v_mag_imbalance,
                voltage_symmetrical=v_symmetrical,
                asset_spec=eff_spec,
                operational_limits=eff_limits,
                derating_config=input_data.derating_config,
                timestamp=calc_ts,
                current_three_phase=i_three_phase,
                stage_name=STAGE_NAME,
            )
            issues.extend(derating_issues)

        # 8. Extract canonical summary measurements
        vuf_meas: Optional[Measurement[float]] = (
            v_symmetrical.negative_sequence_ratio_percent if v_symmetrical else None
        )
        pvur_meas: Optional[Measurement[float]] = (
            v_mag_imbalance.max_deviation_percent if v_mag_imbalance else None
        )
        cuf_meas: Optional[Measurement[float]] = (
            i_symmetrical.negative_sequence_ratio_percent if i_symmetrical else None
        )
        neutral_meas: Optional[Measurement[float]] = (
            i_symmetrical.neutral_current_magnitude if i_symmetrical else None
        )
        derate_factor_meas: Optional[Measurement[float]] = (
            derating_res.derating_factor_pu if derating_res else None
        )

        is_computed = (
            v_mag_imbalance is not None
            or i_mag_imbalance is not None
            or v_symmetrical is not None
            or i_symmetrical is not None
            or derating_res is not None
        )

        provenance_dict: Dict[str, Any] = {
            "pipeline_stage": STAGE_NAME,
            "specification_version": "v2.6.0",
            "asset_id": asset_id,
            "calculation_timestamp": calc_ts.isoformat(),
            "has_voltage_phasors": v_three_phase.has_complex_phasors if v_three_phase else False,
            "has_current_phasors": i_three_phase.has_complex_phasors if i_three_phase else False,
            "derating_status": derating_res.status if derating_res else "UNKNOWN",
            "standards_referenced": [
                {"standard_id": "IEC 61000-4-30", "purpose": "True Voltage Unbalance Factor (VUF)"},
                {"standard_id": "IEC 60076-1", "purpose": "Transformer operational sequence balance"},
                {"standard_id": "IEEE Std 141", "purpose": "Phase Voltage Unbalance Rate (PVUR)"},
            ],
        }

        result = PhaseImbalanceResult(
            is_computed=is_computed,
            voltage_unbalance_factor_vuf=vuf_meas,
            phase_voltage_unbalance_rate_pvur=pvur_meas,
            current_unbalance_factor_cuf=cuf_meas,
            neutral_current_a=neutral_meas,
            derating_factor_pu=derate_factor_meas,
            timestamp=calc_ts,
            asset_id=asset_id,
            voltage_magnitude_imbalance=v_mag_imbalance,
            current_magnitude_imbalance=i_mag_imbalance,
            voltage_symmetrical_components=v_symmetrical,
            current_symmetrical_components=i_symmetrical,
            derating_assessment=derating_res,
            issues=issues,
            calculation_provenance=provenance_dict,
        )

        return result, issues

    def compute_batch_imbalance(
        self,
        batch_inputs: List[PhaseImbalanceInput],
    ) -> Tuple[List[PhaseImbalanceResult], List[ProcessingIssue]]:
        """
        Computes phase imbalance and symmetrical components for a time-series batch of inputs.
        """
        all_results: List[PhaseImbalanceResult] = []
        all_issues: List[ProcessingIssue] = []

        for inp in batch_inputs:
            res, rec_issues = self.compute_imbalance(inp)
            all_results.append(res)
            all_issues.extend(rec_issues)

        return all_results, all_issues
