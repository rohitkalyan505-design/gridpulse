"""
GridPulse — Electrical Calculation Engine
Part of scientific.features.

Coordinates deterministic electrical calculations on validated telemetry records.
Guarantees:
- Output evidence is strictly CALCULATED.
- Measured values are preserved as MEASURED and never silently overwritten.
- Both measured and calculated quantities coexist in ElectricalFeaturesResult.
- Missing inputs produce structured ProcessingIssue diagnostics without zero-fill.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from scientific.contracts.asset import TransformerAssetSpec
from scientific.contracts.enums import EvidenceClassification
from scientific.contracts.issues import ProcessingIssue
from scientific.contracts.measurement import Measurement
from scientific.contracts.results import ElectricalFeaturesResult
from scientific.features.calculations import (
    calculate_apparent_power,
    calculate_power_factor,
    calculate_three_phase_average_current,
    calculate_three_phase_average_voltage,
)
from scientific.validation.contracts import ValidatedTelemetryBatch, ValidatedTelemetryRecord


class ElectricalCalculationEngine:
    """
    Deterministic electrical calculation engine for GridPulse.
    Transforms validated telemetry into ElectricalFeaturesResult containing
    closed-form calculated quantities alongside preserved measured quantities.
    """

    def __init__(self, asset_spec: Optional[TransformerAssetSpec] = None) -> None:
        self.asset_spec = asset_spec

    def compute_record_features(
        self,
        record: ValidatedTelemetryRecord,
        asset_id: Optional[str] = None,
    ) -> Tuple[ElectricalFeaturesResult, List[ProcessingIssue]]:
        """
        Executes deterministic electrical engineering calculations for a single validated record.
        """
        issues: List[ProcessingIssue] = []
        eff_asset_id = asset_id or record.asset_id
        timestamp = record.timestamp
        provenance_dict: Dict[str, Any] = {}

        # 1. Preserve metered phase quantities
        v_a = record.voltage_a
        v_b = record.voltage_b
        v_c = record.voltage_c
        i_a = record.current_a
        i_b = record.current_b
        i_c = record.current_c
        freq = record.frequency
        p = record.active_power_kw
        q = record.reactive_power_kvar

        # 2. Check for directly measured apparent power and power factor
        measured_s: Optional[Measurement[float]] = None
        # Check if record has direct apparent power metered
        if hasattr(record, "apparent_power_kva") and record.apparent_power_kva is not None:
            measured_s = record.apparent_power_kva

        measured_pf: Optional[Measurement[float]] = None
        if record.power_factor is not None:
            # If power factor was directly provided in telemetry, preserve as measured
            measured_pf = record.power_factor

        # 3. Calculate apparent power: S = sqrt(P² + Q²)
        calculated_s: Optional[Measurement[float]] = None
        s_calc, s_issues = calculate_apparent_power(p, q, eff_asset_id, timestamp)
        issues.extend(s_issues)
        if s_calc is not None:
            calculated_s = s_calc
            provenance_dict["apparent_power_from_p_q"] = s_calc.metadata

        # 4. Resolve effective S for PF calculation (prefer calculated or measured)
        effective_s_for_pf = calculated_s or measured_s

        # 5. Calculate power factor: PF = P / S
        calculated_pf: Optional[Measurement[float]] = None
        pf_calc, pf_issues = calculate_power_factor(p, effective_s_for_pf, q, eff_asset_id, timestamp)
        issues.extend(pf_issues)
        if pf_calc is not None:
            calculated_pf = pf_calc
            provenance_dict["power_factor_from_p_s"] = pf_calc.metadata

        # 6. Calculate three-phase average phase RMS voltage: V_avg = (VA + VB + VC) / 3
        v_avg: Optional[Measurement[float]] = None
        v_calc, v_issues = calculate_three_phase_average_voltage(v_a, v_b, v_c, eff_asset_id, timestamp)
        issues.extend(v_issues)
        if v_calc is not None:
            v_avg = v_calc
            provenance_dict["average_phase_voltage_3p"] = v_calc.metadata

        # 7. Calculate three-phase average phase RMS current: I_avg = (IA + IB + IC) / 3
        i_avg: Optional[Measurement[float]] = None
        i_calc, i_issues = calculate_three_phase_average_current(i_a, i_b, i_c, eff_asset_id, timestamp)
        issues.extend(i_issues)
        if i_calc is not None:
            i_avg = i_calc
            provenance_dict["average_phase_current_3p"] = i_calc.metadata

        # 8. Primary resolution preserving coexistence:
        # If measured exists, primary reflects measured, calculated is preserved in coexistence field.
        # If only calculated exists, primary points to calculated.
        primary_s = measured_s or calculated_s
        primary_pf = measured_pf or calculated_pf

        features = ElectricalFeaturesResult(
            is_computed=True,
            v_a_rms=v_a,
            v_b_rms=v_b,
            v_c_rms=v_c,
            v_avg_rms=v_avg,
            i_a_rms=i_a,
            i_b_rms=i_b,
            i_c_rms=i_c,
            i_avg_rms=i_avg,
            active_power_kw=p,
            reactive_power_kvar=q,
            apparent_power_kva=primary_s,
            power_factor=primary_pf,
            frequency_hz=freq,
            # Explicit coexistence fields
            apparent_power_measured_kva=measured_s,
            apparent_power_calculated_kva=calculated_s,
            power_factor_measured=measured_pf,
            power_factor_calculated=calculated_pf,
            calculation_provenance=provenance_dict,
        )

        return features, issues

    def compute_batch_features(
        self,
        batch: ValidatedTelemetryBatch,
    ) -> Tuple[List[ElectricalFeaturesResult], List[ProcessingIssue]]:
        """
        Executes deterministic electrical engineering calculations for all records in a batch.
        """
        all_features: List[ElectricalFeaturesResult] = []
        all_issues: List[ProcessingIssue] = []

        for rec in batch.records:
            feat, rec_issues = self.compute_record_features(rec, batch.asset_id)
            all_features.append(feat)
            all_issues.extend(rec_issues)

        return all_features, all_issues
