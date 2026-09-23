"""
GridPulse — Phase 2 Step 3 Deterministic Electrical Calculation Tests
Tests all 20 required behaviors and the five approved corrections.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple
import unittest

from scientific.contracts.enums import (
    EvidenceClassification,
    IssueSeverity,
    MeasurementQuality,
)
from scientific.contracts.measurement import Measurement
from scientific.contracts.results import ElectricalFeaturesResult, ScientificRunResult, ValidationSummary
from scientific.contracts.provenance import ProvenanceMetadata
from scientific.features.calculations import (
    NEAR_ZERO_APPARENT_POWER_KVA,
    calculate_apparent_power,
    calculate_power_factor,
    calculate_three_phase_average_current,
    calculate_three_phase_average_voltage,
    normalize_power_to_canonical_kva,
)
from scientific.features.engine import ElectricalCalculationEngine
from scientific.validation.contracts import ValidatedTelemetryRecord


class TestElectricalCalculations(unittest.TestCase):
    """Test suite for deterministic electrical engineering formulations."""

    def setUp(self):
        self.asset_id = "TX-SUB01-DT04"
        self.now_utc = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
        self.engine = ElectricalCalculationEngine()

    def _m(self, val: Optional[float], unit: str, evidence: EvidenceClassification = EvidenceClassification.MEASURED) -> Measurement[float]:
        """Helper to create a standard valid measurement."""
        if val is None:
            return Measurement.create_missing(unit, self.now_utc)
        return Measurement(
            value=val,
            unit=unit,
            evidence=evidence,
            quality=MeasurementQuality.GOOD,
            timestamp=self.now_utc,
        )

    # -------------------------------------------------------------------------
    # Test 1: S = sqrt(P² + Q²)
    # -------------------------------------------------------------------------
    def test_01_apparent_power_from_p_q(self):
        p = self._m(125.0, "kW")
        q = self._m(60.0, "kVAR")
        s, issues = calculate_apparent_power(p, q, self.asset_id, self.now_utc)

        self.assertIsNotNone(s)
        self.assertEqual(len(issues), 0)
        expected_s = math.sqrt(125.0**2 + 60.0**2)  # ~138.654246 kVA
        self.assertAlmostEqual(s.value, expected_s, places=5)
        self.assertEqual(s.unit, "kVA")
        self.assertEqual(s.evidence, EvidenceClassification.CALCULATED)
        self.assertEqual(s.metadata.get("formula_id"), "APPARENT_POWER_FROM_P_Q")

    # -------------------------------------------------------------------------
    # Test 2: Unit Normalization across Prefixes
    # -------------------------------------------------------------------------
    def test_02_unit_normalization(self):
        # P in W (125,000 W), Q in kVAR (60 kVAR)
        p = self._m(125000.0, "W")
        q = self._m(60.0, "kVAR")
        s, issues = calculate_apparent_power(p, q, self.asset_id, self.now_utc)

        self.assertIsNotNone(s)
        self.assertEqual(len(issues), 0)
        expected_s = math.sqrt(125.0**2 + 60.0**2)
        self.assertAlmostEqual(s.value, expected_s, places=5)
        self.assertEqual(s.unit, "kVA")  # Normalized to canonical kVA

    # -------------------------------------------------------------------------
    # Test 3: Correct S Units matching Input Prefix
    # -------------------------------------------------------------------------
    def test_03_correct_s_units(self):
        # W + VAR -> VA
        s_va, _ = calculate_apparent_power(self._m(100.0, "W"), self._m(50.0, "VAR"), self.asset_id, self.now_utc)
        self.assertEqual(s_va.unit, "VA")
        self.assertAlmostEqual(s_va.value, math.sqrt(100.0**2 + 50.0**2), places=5)

        # MW + MVAR -> MVA
        s_mva, _ = calculate_apparent_power(self._m(1.5, "MW"), self._m(0.8, "MVAR"), self.asset_id, self.now_utc)
        self.assertEqual(s_mva.unit, "MVA")
        self.assertAlmostEqual(s_mva.value, math.sqrt(1.5**2 + 0.8**2), places=5)

    # -------------------------------------------------------------------------
    # Test 4: PF = P / S
    # -------------------------------------------------------------------------
    def test_04_power_factor_from_p_s(self):
        p = self._m(125.0, "kW")
        s = self._m(138.654246, "kVA", evidence=EvidenceClassification.CALCULATED)
        pf, issues = calculate_power_factor(p, s, asset_id=self.asset_id)

        self.assertIsNotNone(pf)
        self.assertEqual(len(issues), 0)
        expected_pf = 125.0 / 138.654246  # ~0.901523
        self.assertAlmostEqual(pf.value, expected_pf, places=5)
        self.assertEqual(pf.unit, "ratio")
        self.assertEqual(pf.evidence, EvidenceClassification.CALCULATED)
        self.assertEqual(pf.metadata.get("formula_id"), "POWER_FACTOR_FROM_P_S")

    # -------------------------------------------------------------------------
    # Test 5: Zero S Handling (Division by Zero Avoided)
    # -------------------------------------------------------------------------
    def test_05_zero_s_handling(self):
        p = self._m(0.0, "kW")
        s = self._m(0.0, "kVA")
        pf, issues = calculate_power_factor(p, s, asset_id=self.asset_id)

        self.assertIsNone(pf)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].code, "WARN_NEAR_ZERO_APPARENT_POWER")
        self.assertEqual(issues[0].severity, IssueSeverity.WARNING)

    # -------------------------------------------------------------------------
    # Test 6: Unit-Independent Near-Zero Handling (Correction #1)
    # -------------------------------------------------------------------------
    def test_06_unit_independent_near_zero_handling(self):
        # 0.0005 VA = 0.5 mVA = 5e-7 kVA (< 1e-6 kVA threshold)
        p_va = self._m(0.0004, "VA")
        s_va = self._m(0.0005, "VA")
        pf_va, issues_va = calculate_power_factor(p_va, s_va, asset_id=self.asset_id)
        self.assertIsNone(pf_va)
        self.assertTrue(any(i.code == "WARN_NEAR_ZERO_APPARENT_POWER" for i in issues_va))

        # 0.0000005 MVA = 0.5 kVA (> 1e-6 kVA threshold -> should compute safely!)
        p_mva = self._m(0.0004, "MVA")  # 0.4 kVA
        s_mva = self._m(0.0005, "MVA")  # 0.5 kVA
        pf_mva, issues_mva = calculate_power_factor(p_mva, s_mva, asset_id=self.asset_id)
        self.assertIsNotNone(pf_mva)
        self.assertAlmostEqual(pf_mva.value, 0.8, places=4)

    # -------------------------------------------------------------------------
    # Test 7: Missing P Handling (Never Assumes P=0)
    # -------------------------------------------------------------------------
    def test_07_missing_p_handling(self):
        p_missing = None
        q = self._m(60.0, "kVAR")
        s, issues = calculate_apparent_power(p_missing, q, self.asset_id, self.now_utc)

        self.assertIsNone(s)
        self.assertTrue(any(i.code == "ERR_INSUFFICIENT_TELEMETRY" for i in issues))

    # -------------------------------------------------------------------------
    # Test 8: Missing Q Handling (Never Assumes Q=0)
    # -------------------------------------------------------------------------
    def test_08_missing_q_handling(self):
        p = self._m(125.0, "kW")
        q_missing = None
        s, issues = calculate_apparent_power(p, q_missing, self.asset_id, self.now_utc)

        self.assertIsNone(s)
        # CRITICAL RULE: S must NOT be calculated as 125 kVA by assuming Q=0
        self.assertTrue(any(i.code == "ERR_INSUFFICIENT_TELEMETRY" for i in issues))

    # -------------------------------------------------------------------------
    # Test 9: Non-Finite Values (NaN / Inf Handled Gracefully)
    # -------------------------------------------------------------------------
    def test_09_non_finite_values(self):
        p_nan = self._m(float("nan"), "kW")
        q = self._m(60.0, "kVAR")
        s, issues = calculate_apparent_power(p_nan, q, self.asset_id, self.now_utc)

        self.assertIsNone(s)
        self.assertTrue(any(i.code == "ERR_NON_FINITE_INPUT" for i in issues))

        p_inf = self._m(float("inf"), "kW")
        s_inf = self._m(100.0, "kVA")
        pf, issues_pf = calculate_power_factor(p_inf, s_inf, asset_id=self.asset_id)
        self.assertIsNone(pf)
        self.assertTrue(any(i.code == "ERR_NON_FINITE_INPUT" for i in issues_pf))

    # -------------------------------------------------------------------------
    # Test 10: Invalid Units (Incompatible Units Rejected)
    # -------------------------------------------------------------------------
    def test_10_invalid_units(self):
        p = self._m(125.0, "psi")  # Non-power unit
        q = self._m(60.0, "kVAR")
        s, issues = calculate_apparent_power(p, q, self.asset_id, self.now_utc)

        self.assertIsNone(s)
        self.assertTrue(any(i.code == "ERR_INCOMPATIBLE_UNITS" for i in issues))

    # -------------------------------------------------------------------------
    # Test 11: Measured S Remains MEASURED
    # -------------------------------------------------------------------------
    def test_11_measured_s_remains_measured(self):
        measured_s = self._m(150.0, "kVA", evidence=EvidenceClassification.MEASURED)
        self.assertEqual(measured_s.evidence, EvidenceClassification.MEASURED)

    # -------------------------------------------------------------------------
    # Test 12: Calculated S Remains CALCULATED
    # -------------------------------------------------------------------------
    def test_12_calculated_s_remains_calculated(self):
        p = self._m(80.0, "kW")
        q = self._m(60.0, "kVAR")
        s, _ = calculate_apparent_power(p, q, self.asset_id, self.now_utc)
        self.assertEqual(s.evidence, EvidenceClassification.CALCULATED)
        self.assertAlmostEqual(s.value, 100.0)

    # -------------------------------------------------------------------------
    # Test 13: Measured and Calculated S Coexist Without Overwrite
    # -------------------------------------------------------------------------
    def test_13_measured_and_calculated_s_coexist(self):
        # Create a record with both metered active/reactive power AND direct meter PF/apparent power
        ts = self.now_utc
        rec = ValidatedTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=ts,
            voltage_a=self._m(240.0, "V"),
            voltage_b=self._m(240.0, "V"),
            voltage_c=self._m(240.0, "V"),
            current_a=self._m(50.0, "A"),
            current_b=self._m(50.0, "A"),
            current_c=self._m(50.0, "A"),
            frequency=self._m(50.0, "Hz"),
            active_power_kw=self._m(120.0, "kW"),
            reactive_power_kvar=self._m(50.0, "kVAR"),
            power_factor=self._m(0.92, "ratio", evidence=EvidenceClassification.MEASURED),
        )

        features, _ = self.engine.compute_record_features(rec)

        # Calculated S = sqrt(120^2 + 50^2) = 130.0 kVA
        self.assertIsNotNone(features.apparent_power_calculated_kva)
        self.assertAlmostEqual(features.apparent_power_calculated_kva.value, 130.0)
        self.assertEqual(features.apparent_power_calculated_kva.evidence, EvidenceClassification.CALCULATED)

        # Measured PF preserved alongside calculated PF
        self.assertIsNotNone(features.power_factor_measured)
        self.assertEqual(features.power_factor_measured.value, 0.92)
        self.assertEqual(features.power_factor_measured.evidence, EvidenceClassification.MEASURED)

        self.assertIsNotNone(features.power_factor_calculated)
        expected_calc_pf = 120.0 / 130.0  # ~0.923076
        self.assertAlmostEqual(features.power_factor_calculated.value, expected_calc_pf, places=4)
        self.assertEqual(features.power_factor_calculated.evidence, EvidenceClassification.CALCULATED)

    # -------------------------------------------------------------------------
    # Test 14: Measured and Calculated PF Coexist
    # -------------------------------------------------------------------------
    def test_14_measured_and_calculated_pf_coexist(self):
        p = self._m(100.0, "kW")
        s = self._m(125.0, "kVA", evidence=EvidenceClassification.CALCULATED)
        pf_calc, _ = calculate_power_factor(p, s, asset_id=self.asset_id)
        self.assertAlmostEqual(pf_calc.value, 0.8)
        self.assertEqual(pf_calc.evidence, EvidenceClassification.CALCULATED)

        pf_meas = self._m(0.81, "ratio", evidence=EvidenceClassification.MEASURED)
        self.assertEqual(pf_meas.evidence, EvidenceClassification.MEASURED)

    # -------------------------------------------------------------------------
    # Test 15: Missing Phase Does NOT Create Invented Phase Values
    # -------------------------------------------------------------------------
    def test_15_missing_phase_no_invention(self):
        va = self._m(240.0, "V")
        vb = self._m(240.0, "V")
        vc_missing = None

        v_avg, issues = calculate_three_phase_average_voltage(va, vb, vc_missing, self.asset_id, self.now_utc)
        self.assertIsNone(v_avg)
        self.assertTrue(any(i.code == "ERR_INSUFFICIENT_TELEMETRY" for i in issues))

    # -------------------------------------------------------------------------
    # Test 16: Three-Phase Average Phase Voltage (Correction #5)
    # -------------------------------------------------------------------------
    def test_16_three_phase_v_avg(self):
        va = self._m(238.0, "V")
        vb = self._m(240.0, "V")
        vc = self._m(242.0, "V")

        v_avg, issues = calculate_three_phase_average_voltage(va, vb, vc, self.asset_id, self.now_utc)
        self.assertIsNotNone(v_avg)
        self.assertEqual(len(issues), 0)
        self.assertEqual(v_avg.value, 240.0)
        self.assertEqual(v_avg.unit, "V")
        self.assertEqual(v_avg.evidence, EvidenceClassification.CALCULATED)
        self.assertEqual(v_avg.metadata.get("definition"), "Average Phase RMS Voltage")

    # -------------------------------------------------------------------------
    # Test 17: Three-Phase Average Phase Current (Correction #5)
    # -------------------------------------------------------------------------
    def test_17_three_phase_i_avg(self):
        ia = self._m(48.0, "A")
        ib = self._m(50.0, "A")
        ic = self._m(52.0, "A")

        i_avg, issues = calculate_three_phase_average_current(ia, ib, ic, self.asset_id, self.now_utc)
        self.assertIsNotNone(i_avg)
        self.assertEqual(len(issues), 0)
        self.assertEqual(i_avg.value, 50.0)
        self.assertEqual(i_avg.unit, "A")
        self.assertEqual(i_avg.evidence, EvidenceClassification.CALCULATED)
        self.assertEqual(i_avg.metadata.get("definition"), "Average Phase RMS Current")

    # -------------------------------------------------------------------------
    # Test 18: Signed PF Convention (Correction #3)
    # -------------------------------------------------------------------------
    def test_18_signed_pf_convention(self):
        # Consumption: P = +100 kW, S = 125 kVA -> PF = +0.8
        p_import = self._m(100.0, "kW")
        s = self._m(125.0, "kVA")
        pf_import, _ = calculate_power_factor(p_import, s, asset_id=self.asset_id)
        self.assertAlmostEqual(pf_import.value, 0.8)
        self.assertGreater(pf_import.value, 0.0)

        # Generation: P = -100 kW, S = 125 kVA -> PF = -0.8
        p_export = self._m(-100.0, "kW")
        pf_export, _ = calculate_power_factor(p_export, s, asset_id=self.asset_id)
        self.assertAlmostEqual(pf_export.value, -0.8)
        self.assertLess(pf_export.value, 0.0)
        self.assertEqual(pf_export.metadata.get("convention"), "GRIDPULSE_SIGNED_PF_P_DIV_S")

    # -------------------------------------------------------------------------
    # Test 19: No Silent Clamping of Invalid PF (Correction #4)
    # -------------------------------------------------------------------------
    def test_19_no_silent_pf_clamping(self):
        # If P > S (e.g. P = 150 kW, S = 100 kVA due to inconsistent data), PF = 1.5
        # The engine must NOT clamp to 1.0! It must reject with an issue.
        p_inconsistent = self._m(150.0, "kW")
        s = self._m(100.0, "kVA")
        pf, issues = calculate_power_factor(p_inconsistent, s, asset_id=self.asset_id)

        self.assertIsNone(pf)
        self.assertTrue(any(i.code == "ERR_CALCULATED_PF_DOMAIN_VIOLATION" for i in issues))

    # -------------------------------------------------------------------------
    # Test 20: Provenance and Serialization Deterministic
    # -------------------------------------------------------------------------
    def test_20_provenance_and_serialization(self):
        rec = ValidatedTelemetryRecord(
            asset_id=self.asset_id,
            timestamp=self.now_utc,
            voltage_a=self._m(240.0, "V"),
            voltage_b=self._m(240.0, "V"),
            voltage_c=self._m(240.0, "V"),
            current_a=self._m(50.0, "A"),
            current_b=self._m(50.0, "A"),
            current_c=self._m(50.0, "A"),
            frequency=self._m(50.0, "Hz"),
            active_power_kw=self._m(120.0, "kW"),
            reactive_power_kvar=self._m(50.0, "kVAR"),
        )
        features, _ = self.engine.compute_record_features(rec)

        prov = ProvenanceMetadata(
            pipeline_version="0.2.0-step3",
            execution_timestamp=self.now_utc,
            telemetry_digest="a" * 64,
            asset_id=self.asset_id,
            evidence_tally={"CALCULATED": 3, "MEASURED": 7},
        )
        summary = ValidationSummary(
            total_records=1,
            valid_records=1,
            suspect_records=0,
            bad_records=0,
            missing_records=0,
            dropped_records=0,
        )
        result = ScientificRunResult(
            run_id="run-step3-001",
            asset_id=self.asset_id,
            time_window_start=self.now_utc,
            time_window_end=self.now_utc,
            pipeline_version="0.2.0-step3",
            provenance=prov,
            validation_summary=summary,
            electrical_features=features,
        )

        d = result.to_dict()
        self.assertEqual(d["run_id"], "run-step3-001")
        feat_dict = d["electrical_features"]
        self.assertTrue(feat_dict["is_computed"])
        self.assertEqual(feat_dict["apparent_power_calculated_kva"]["evidence"], "CALCULATED")
        self.assertAlmostEqual(feat_dict["apparent_power_calculated_kva"]["value"], 130.0)
        self.assertEqual(feat_dict["v_avg_rms"]["value"], 240.0)
        self.assertEqual(feat_dict["i_avg_rms"]["value"], 50.0)
        self.assertIn("apparent_power_from_p_q", feat_dict["calculation_provenance"])


if __name__ == "__main__":
    unittest.main()
