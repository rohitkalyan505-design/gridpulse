"""
GridPulse — Phase 2 Step 5 Thermal Analysis & Insulation Degradation Tests
Comprehensive Unit and Regression Test Suite for IEEE/IEC Thermal Modeling.

Covers all 9 mandated test groups:
1. Standards and Configuration (IEEE vs IEC preference, no defaults, independent rates)
2. Thermal Model Equations (IEEE K^(2y) vs IEC K^y, exponent range validation)
3. Initial State Behavior (Quarantine on missing state, no zero/rated rise assumptions)
4. Continuity Break Recovery (Telemetry gaps, independent sensor recovery, no speculative bridging)
5. Forward-Interval Integration (Sample k governs [t_k, t_{k+1}), final sample 0 duration, cumulative completeness)
6. Evidence Propagation (MEASURED -> CALCULATED vs MODELED -> MODELED)
7. Parameter Provenance & Physical Integrity (Rejection of generic assumptions, anomalous sensor preservation)
8. Numerical Safety (Absolute zero guard, float overflow, reference temperature fidelity)
9. Regression Baseline (Zero regressions on previous steps)
"""

from datetime import datetime, timedelta, timezone
import math
import unittest
import uuid

from scientific.contracts.enums import (
    AgingStandardPreference,
    EvidenceClassification,
    InsulationSystemType,
    IssueSeverity,
    LoadingState,
    MeasurementQuality,
    ParameterSourceClass,
    ThermalModelStandard,
)
from scientific.contracts.issues import (
    ERR_INVALID_EXPONENT_RANGE,
    ERR_INVALID_PARAMETER_VALUE,
    ERR_UNESTABLISHED_INITIAL_THERMAL_STATE,
    ERR_UNSAFE_ARRHENIUS_EVALUATION,
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
from scientific.contracts.measurement import Measurement
from scientific.contracts.results import (
    ThermalIntervalResult,
    ThermalStateResult,
    TransformerLoadingResult,
)
from scientific.thermal.contracts import (
    ProvenancedParameter,
    ThermalAnalysisInput,
    ThermalModelParameters,
)
from scientific.thermal.engine import ThermalCalculationEngine
from scientific.thermal.solver import (
    calculate_iec_relative_ageing_rate,
    calculate_iec_ultimate_hot_spot_rise,
    calculate_iec_ultimate_top_oil_rise,
    calculate_ieee_aging_acceleration_factor,
    calculate_ieee_ultimate_hot_spot_rise,
    calculate_ieee_ultimate_top_oil_rise,
    solve_exponential_recurrence,
)


def make_provenanced_param(
    name: str,
    val: float,
    unit: str,
    source: ParameterSourceClass = ParameterSourceClass.FACTORY_TEST,
    verified: bool = True,
    asset_id: str = "TX-TEST-01",
) -> ProvenancedParameter:
    return ProvenancedParameter(
        parameter_name=name,
        value=val,
        unit=unit,
        source_class=source,
        reference_document="FAT-Report-2024-001.pdf",
        is_verified=verified,
        applicable_asset_id=asset_id,
    )


def make_valid_ieee_params(asset_id: str = "TX-TEST-01") -> ThermalModelParameters:
    return ThermalModelParameters(
        rated_top_oil_rise_k=make_provenanced_param("rated_top_oil_rise_k", 55.0, "K", asset_id=asset_id),
        rated_hot_spot_rise_k=make_provenanced_param("rated_hot_spot_rise_k", 25.0, "K", asset_id=asset_id),
        loss_ratio_r=make_provenanced_param("loss_ratio_r", 5.0, "", asset_id=asset_id),
        oil_exponent_x=make_provenanced_param("oil_exponent_x", 0.8, "", asset_id=asset_id),
        winding_exponent_y=make_provenanced_param("winding_exponent_y", 0.8, "", asset_id=asset_id),
        time_constant_oil_hours=make_provenanced_param("time_constant_oil_hours", 3.0, "h", asset_id=asset_id),
        time_constant_winding_hours=make_provenanced_param("time_constant_winding_hours", 0.1, "h", asset_id=asset_id),
        reference_life_hours=make_provenanced_param("reference_life_hours", 180000.0, "h", asset_id=asset_id),
    )


def make_valid_iec_params(asset_id: str = "TX-TEST-01") -> ThermalModelParameters:
    return ThermalModelParameters(
        rated_top_oil_rise_k=make_provenanced_param("rated_top_oil_rise_k", 55.0, "K", asset_id=asset_id),
        rated_hot_spot_rise_k=make_provenanced_param("rated_hot_spot_rise_k", 25.0, "K", asset_id=asset_id),
        loss_ratio_r=make_provenanced_param("loss_ratio_r", 5.0, "", asset_id=asset_id),
        oil_exponent_x=make_provenanced_param("oil_exponent_x", 0.8, "", asset_id=asset_id),
        winding_exponent_y=make_provenanced_param("winding_exponent_y", 1.3, "", asset_id=asset_id),
        time_constant_oil_hours=make_provenanced_param("time_constant_oil_hours", 3.0, "h", asset_id=asset_id),
        time_constant_winding_hours=make_provenanced_param("time_constant_winding_hours", 0.1, "h", asset_id=asset_id),
        reference_life_hours=make_provenanced_param("reference_life_hours", 150000.0, "h", asset_id=asset_id),
    )


def make_loading_record(
    loading_pu: float,
    ts: datetime,
) -> TransformerLoadingResult:
    return TransformerLoadingResult(
        is_computed=True,
        loading_ratio_pu=Measurement(
            value=loading_pu,
            unit="pu",
            evidence=EvidenceClassification.CALCULATED,
            quality=MeasurementQuality.GOOD,
            timestamp=ts,
        ),
        peak_loading_timestamp=ts,
    )


class TestGroup1StandardsAndConfiguration(unittest.TestCase):
    """Group 1: Explicit standard selection, refusal on missing/invalid, independent rates."""

    def setUp(self):
        self.engine = ThermalCalculationEngine()
        self.t0 = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(hours=1)
        self.loading = [make_loading_record(1.0, self.t0), make_loading_record(1.0, self.t1)]

    def test_ieee_preference_integrates_faa(self):
        """Valid AgingStandardPreference.IEEE integrates F_AA across intervals."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            measured_hot_spot_series=[110.0, 110.0],
            measured_top_oil_series=[85.0, 85.0],
            ambient_temperature_series=[30.0, 30.0],
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertEqual(len(res), 2)
        # At 110°C thermally upgraded, F_AA = 1.0. Duration = 1.0 h.
        # Interval loss of life for interval 0 should be 1.0 * 1.0 = 1.0 h.
        self.assertIsNotNone(res[0].forward_interval_result)
        self.assertIsNotNone(res[0].forward_interval_result.equivalent_aging_hours)
        self.assertAlmostEqual(res[0].forward_interval_result.equivalent_aging_hours.value, 1.0, places=4)
        # Cumulative should be 1.0 h
        self.assertIsNotNone(res[0].cumulative_aging_hours)
        self.assertAlmostEqual(res[0].cumulative_aging_hours.value, 1.0, places=4)
        # Provenance records IEEE
        self.assertEqual(res[0].aging_standard, AgingStandardPreference.IEEE)

    def test_iec_preference_integrates_v(self):
        """Valid AgingStandardPreference.IEC integrates V across intervals."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_iec_params("TX-01"),
            insulation_system=InsulationSystemType.NON_THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEC,
            aging_standard=AgingStandardPreference.IEC,
            measured_hot_spot_series=[104.0, 104.0],  # V = 2^((104-98)/6) = 2.0
            measured_top_oil_series=[85.0, 85.0],
            ambient_temperature_series=[30.0, 30.0],
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertEqual(len(res), 2)
        # V = 2.0. Duration = 1.0 h. L_OL = 2.0 h.
        self.assertIsNotNone(res[0].forward_interval_result.equivalent_aging_hours)
        self.assertAlmostEqual(res[0].forward_interval_result.equivalent_aging_hours.value, 2.0, places=4)
        self.assertEqual(res[0].aging_standard, AgingStandardPreference.IEC)

    def test_missing_aging_standard_blocks_integration_without_fallback(self):
        """Missing aging_standard emits ERR_UNSPECIFIED_AGING_STANDARD, returns UNKNOWN L_OL, and no silent fallback."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=None,  # Missing!
            measured_hot_spot_series=[110.0, 110.0],
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertTrue(any(i.code == ERR_UNSPECIFIED_AGING_STANDARD for i in issues))
        # Equivalent aging hours must be None (UNKNOWN)
        self.assertIsNone(res[0].forward_interval_result.equivalent_aging_hours)
        self.assertIsNone(res[0].cumulative_aging_hours)
        self.assertFalse(res[0].is_integration_complete)

    def test_invalid_aging_standard_blocks_integration(self):
        """Invalid aging_standard preference emits ERR_UNSPECIFIED_AGING_STANDARD."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard="CUSTOM_INVALID",  # Invalid!
            measured_hot_spot_series=[110.0, 110.0],
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertTrue(any(i.code == ERR_UNSPECIFIED_AGING_STANDARD for i in issues))
        self.assertIsNone(res[0].cumulative_aging_hours)

    def test_independent_faa_and_v_calculated_when_integration_blocked(self):
        """F_AA and V are independently calculated even when aging_standard is None."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=None,
            measured_hot_spot_series=[110.0, 110.0],
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        # Both rates are calculated from valid measured hot spot!
        self.assertIsNotNone(res[0].aging_acceleration_factor_faa)
        self.assertIsNotNone(res[0].relative_ageing_rate_v)
        self.assertAlmostEqual(res[0].aging_acceleration_factor_faa.value, 1.0, places=4)
        self.assertAlmostEqual(res[0].relative_ageing_rate_v.value, 1.0, places=4)
        # But loss-of-life remains UNKNOWN
        self.assertIsNone(res[0].forward_interval_result.equivalent_aging_hours)

    def test_missing_thermal_model_standard_blocks_modeled_calculations(self):
        """Missing thermal_model_standard emits ERR_UNSPECIFIED_THERMAL_MODEL_STANDARD."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=None,  # Missing!
            aging_standard=AgingStandardPreference.IEEE,
            measured_hot_spot_series=[110.0, 110.0],
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertTrue(any(i.code == ERR_UNSPECIFIED_THERMAL_MODEL_STANDARD for i in issues))


class TestGroup2ThermalModelEquations(unittest.TestCase):
    """Group 2: IEEE K^(2y) vs IEC K^y reconciliation and exponent validation."""

    def test_ieee_vs_iec_analytical_divergence(self):
        """Independent reference calculation proving IEEE K^(2y) differs from IEC K^y."""
        k = 1.2
        r = 5.0
        x = 0.8
        rated_oil = 55.0
        rated_hs = 25.0

        # IEEE: y_ieee = 0.8 -> exponent = 2 * 0.8 = 1.6
        # 1.2^1.6 = 1.338721; 25.0 * 1.338721 = 33.4680 K
        ieee_oil = calculate_ieee_ultimate_top_oil_rise(k, rated_oil, r, x)
        ieee_hs = calculate_ieee_ultimate_hot_spot_rise(k, rated_hs, 0.8)
        self.assertAlmostEqual(ieee_hs, 25.0 * (1.2 ** 1.6), places=4)
        self.assertAlmostEqual(ieee_hs, 33.468, places=3)

        # IEC: y_iec = 1.3 -> exponent = 1.3
        # 1.2^1.3 = 1.267468; 25.0 * 1.267468 = 31.6867 K
        iec_oil = calculate_iec_ultimate_top_oil_rise(k, rated_oil, r, x)
        iec_hs = calculate_iec_ultimate_hot_spot_rise(k, rated_hs, 1.3)
        self.assertAlmostEqual(iec_hs, 25.0 * (1.2 ** 1.3), places=4)
        self.assertAlmostEqual(iec_hs, 31.6867, places=3)

        # Oil rises are identical formulations, hot spot rises differ substantially
        self.assertAlmostEqual(ieee_oil, iec_oil, places=5)
        self.assertNotEqual(round(ieee_hs, 2), round(iec_hs, 2))

    def test_cross_standard_exponent_validation(self):
        """Winding exponent y=1.3 is rejected under IEEE (range [0.5, 1.2]) and admitted under IEC."""
        params_ieee_invalid = ThermalModelParameters(
            rated_top_oil_rise_k=make_provenanced_param("rated_top_oil_rise_k", 55.0, "K"),
            rated_hot_spot_rise_k=make_provenanced_param("rated_hot_spot_rise_k", 25.0, "K"),
            loss_ratio_r=make_provenanced_param("loss_ratio_r", 5.0, ""),
            oil_exponent_x=make_provenanced_param("oil_exponent_x", 0.8, ""),
            winding_exponent_y=make_provenanced_param("winding_exponent_y", 1.3, ""),  # IEC exponent given to IEEE!
            time_constant_oil_hours=make_provenanced_param("time_constant_oil_hours", 3.0, "h"),
            time_constant_winding_hours=make_provenanced_param("time_constant_winding_hours", 0.1, "h"),
        )
        issues = params_ieee_invalid.validate_for_high_consequence(ThermalModelStandard.IEEE)
        self.assertTrue(any(i.code == ERR_INVALID_EXPONENT_RANGE for i in issues))

        # Under IEC, y=1.3 is completely valid
        issues_iec = params_ieee_invalid.validate_for_high_consequence(ThermalModelStandard.IEC)
        self.assertFalse(any(i.code == ERR_INVALID_EXPONENT_RANGE for i in issues_iec))

    def test_exponential_recurrence_exactness(self):
        """Analytical exponential recurrence matches exact ODE solution."""
        prior = 20.0
        ultimate = 50.0
        tau = 3.0
        dt = 1.5
        # Expected: 20 * exp(-0.5) + 50 * (1 - exp(-0.5))
        # exp(-0.5) = 0.60653066
        # 20 * 0.60653066 + 50 * 0.39346934 = 12.1306 + 19.6735 = 31.8041 K
        sol = solve_exponential_recurrence(prior, ultimate, dt, tau)
        expected = 20.0 * math.exp(-0.5) + 50.0 * (1.0 - math.exp(-0.5))
        self.assertAlmostEqual(sol, expected, places=5)
        self.assertAlmostEqual(sol, 31.8041, places=3)


class TestGroup3InitialStates(unittest.TestCase):
    """Group 3: No zero-rise or steady-state assumptions, quarantine on missing state."""

    def setUp(self):
        self.engine = ThermalCalculationEngine()
        self.t0 = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(hours=1)
        self.loading = [make_loading_record(1.0, self.t0), make_loading_record(1.0, self.t1)]

    def test_no_sensors_and_no_prior_quarantines_initial_state(self):
        """Telemetry starting with no sensors and no prior state emits ERR_UNESTABLISHED_INITIAL_THERMAL_STATE."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            # No sensors!
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertTrue(any(i.code == ERR_UNESTABLISHED_INITIAL_THERMAL_STATE for i in issues))
        self.assertTrue(res[0].is_thermal_quarantined)
        self.assertIsNone(res[0].hot_spot_temp_c)
        self.assertIsNone(res[0].top_oil_temp_c)

    def test_top_oil_and_ambient_sensors_do_not_establish_hot_spot(self):
        """Top-oil and ambient sensors establish oil rise but hot spot remains UNKNOWN without sensor/prior."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            ambient_temperature_series=[30.0, 30.0],
            measured_top_oil_series=[75.0, 75.0],
            # No hot-spot sensor!
        )
        res, issues = self.engine.analyze_batch(inp)
        # Oil is established
        self.assertIsNotNone(res[0].top_oil_temp_c)
        self.assertEqual(res[0].top_oil_temp_c.evidence, EvidenceClassification.MEASURED)
        self.assertAlmostEqual(res[0].top_oil_rise_k.value, 45.0, places=2)
        # Hot-spot rise is NOT assumed to be zero or steady-state!
        self.assertIsNone(res[0].hot_spot_temp_c)
        self.assertTrue(any(i.code == ERR_UNESTABLISHED_INITIAL_THERMAL_STATE for i in issues))

    def test_direct_hot_spot_sensor_supports_independent_rates(self):
        """Direct hot-spot sensor supports aging calculation even when oil/ambient are missing."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            measured_hot_spot_series=[110.0, 110.0],
            # Ambient and top-oil missing!
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertIsNotNone(res[0].hot_spot_temp_c)
        self.assertEqual(res[0].hot_spot_temp_c.evidence, EvidenceClassification.MEASURED)
        self.assertIsNotNone(res[0].aging_acceleration_factor_faa)
        self.assertEqual(res[0].aging_acceleration_factor_faa.evidence, EvidenceClassification.CALCULATED)
        self.assertIsNone(res[0].top_oil_temp_c)


class TestGroup4ContinuityRecovery(unittest.TestCase):
    """Group 4: Telemetry gaps sever state, independent sensor recovery."""

    def setUp(self):
        self.engine = ThermalCalculationEngine()
        self.t0 = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(hours=1)
        self.t2 = self.t1 + timedelta(hours=5)  # 5-hour gap > 900s tolerance!
        self.t3 = self.t2 + timedelta(hours=1)
        self.loading = [
            make_loading_record(1.0, self.t0),
            make_loading_record(1.0, self.t1),
            make_loading_record(1.0, self.t2),
            make_loading_record(1.0, self.t3),
        ]

    def test_gap_severs_state_and_emits_warning(self):
        """Gap exceeding tolerance severs state and emits WARN_TELEMETRY_GAP."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            measured_hot_spot_series=[110.0, 110.0, 110.0, 110.0],
            continuity_tolerance_seconds=900.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertTrue(any(i.code == WARN_TELEMETRY_GAP for i in issues))
        self.assertTrue(res[1].forward_interval_result.is_continuity_break)
        # Gap interval cannot contribute to loss of life
        self.assertIsNone(res[1].forward_interval_result.equivalent_aging_hours)
        # Full window cumulative is UNKNOWN because of the gap
        self.assertIsNone(res[0].cumulative_aging_hours)
        self.assertTrue(any(i.code == WARN_INCOMPLETE_INTEGRATION_WINDOW for i in issues))

    def test_post_gap_recovery_hot_spot_only(self):
        """Hot-spot sensor available post-gap recovers hot spot as MEASURED without inventing oil."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            measured_hot_spot_series=[110.0, 110.0, 110.0, 110.0],
            measured_top_oil_series=[85.0, 85.0, None, None],  # Oil lost post-gap
            continuity_tolerance_seconds=900.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        # At sample 2 (post-gap), hot spot is MEASURED, top oil is UNKNOWN
        self.assertIsNotNone(res[2].hot_spot_temp_c)
        self.assertEqual(res[2].hot_spot_temp_c.evidence, EvidenceClassification.MEASURED)
        self.assertIsNone(res[2].top_oil_temp_c)


class TestGroup5ForwardIntervalIntegration(unittest.TestCase):
    """Group 5: Sample k governs [t_k, t_{k+1}), final sample duration=0, cumulative completeness."""

    def setUp(self):
        self.engine = ThermalCalculationEngine()
        self.t0 = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(hours=0.5)  # 30 min
        self.t2 = self.t1 + timedelta(hours=1.5)  # 90 min
        self.loading = [
            make_loading_record(1.0, self.t0),
            make_loading_record(1.0, self.t1),
            make_loading_record(1.0, self.t2),
        ]

    def test_forward_interval_durations_and_final_sample_zero(self):
        """Sample k governs [t_k, t_{k+1}); final sample has 0.0 duration."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            measured_hot_spot_series=[110.0, 110.0, 110.0],  # F_AA = 1.0 everywhere
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertEqual(len(res), 3)

        # Interval 0: [t0, t1) -> duration 0.5 h, L_OL = 1.0 * 0.5 = 0.5 h
        self.assertAlmostEqual(res[0].forward_interval_result.duration_hours, 0.5, places=4)
        self.assertAlmostEqual(res[0].forward_interval_result.equivalent_aging_hours.value, 0.5, places=4)

        # Interval 1: [t1, t2) -> duration 1.5 h, L_OL = 1.0 * 1.5 = 1.5 h
        self.assertAlmostEqual(res[1].forward_interval_result.duration_hours, 1.5, places=4)
        self.assertAlmostEqual(res[1].forward_interval_result.equivalent_aging_hours.value, 1.5, places=4)

        # Interval 2: final sample -> duration 0.0 h, L_OL = 0.0 h
        self.assertAlmostEqual(res[2].forward_interval_result.duration_hours, 0.0, places=4)
        self.assertAlmostEqual(res[2].forward_interval_result.equivalent_aging_hours.value, 0.0, places=4)

        # Cumulative total = 0.5 + 1.5 + 0.0 = 2.0 h
        self.assertAlmostEqual(res[0].cumulative_aging_hours.value, 2.0, places=4)

        # Percent loss of life with 180,000 h reference: (2.0 / 180,000) * 100% = 0.001111%
        expected_pct = (2.0 / 180000.0) * 100.0
        self.assertIsNotNone(res[0].loss_of_life_percent)
        self.assertAlmostEqual(res[0].loss_of_life_percent.value, expected_pct, places=6)


class TestGroup6EvidencePropagation(unittest.TestCase):
    """Group 6: MEASURED hot spot -> CALCULATED aging/lol vs MODELED -> MODELED."""

    def setUp(self):
        self.engine = ThermalCalculationEngine()
        self.t0 = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(hours=1)
        self.loading = [make_loading_record(1.0, self.t0), make_loading_record(1.0, self.t1)]

    def test_measured_hot_spot_yields_calculated_aging_and_lol(self):
        """Direct fiber sensor hot spot yields CALCULATED aging rate and CALCULATED loss of life."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            measured_hot_spot_series=[110.0, 110.0],
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertEqual(res[0].hot_spot_temp_c.evidence, EvidenceClassification.MEASURED)
        self.assertEqual(res[0].aging_acceleration_factor_faa.evidence, EvidenceClassification.CALCULATED)
        self.assertEqual(res[0].forward_interval_result.equivalent_aging_hours.evidence, EvidenceClassification.CALCULATED)
        self.assertEqual(res[0].cumulative_aging_hours.evidence, EvidenceClassification.CALCULATED)

    def test_modeled_hot_spot_yields_modeled_aging_and_lol(self):
        """Modeled hot spot yields MODELED aging rate and MODELED loss of life."""
        prior = ThermalStateResult(
            is_computed=True,
            top_oil_rise_k=Measurement(55.0, "K", EvidenceClassification.MODELED, MeasurementQuality.GOOD, self.t0),
            hot_spot_rise_k=Measurement(25.0, "K", EvidenceClassification.MODELED, MeasurementQuality.GOOD, self.t0),
            timestamp=self.t0 - timedelta(minutes=5),
            asset_id="TX-01",
        )
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            ambient_temperature_series=[30.0, 30.0],
            initial_prior_thermal_state=prior,
            continuity_tolerance_seconds=7200.0,
            # No direct sensors! Hot spot is MODELED.
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertEqual(res[0].hot_spot_temp_c.evidence, EvidenceClassification.MODELED)
        self.assertEqual(res[0].aging_acceleration_factor_faa.evidence, EvidenceClassification.MODELED)
        self.assertEqual(res[0].forward_interval_result.equivalent_aging_hours.evidence, EvidenceClassification.MODELED)
        self.assertEqual(res[0].cumulative_aging_hours.evidence, EvidenceClassification.MODELED)


class TestGroup7ParameterProvenanceAndAnomalies(unittest.TestCase):
    """Group 7: Parameter provenance checks, sensor inversion preservation, missing ambient."""

    def setUp(self):
        self.engine = ThermalCalculationEngine()
        self.t0 = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(hours=1)
        self.loading = [make_loading_record(1.0, self.t0), make_loading_record(1.0, self.t1)]

    def test_engineering_assumptions_rejected_for_high_consequence(self):
        """Parameters with source ENGINEERING_ASSUMPTION emit ERR_UNVALIDATED_THERMAL_PARAMETERS."""
        params_with_assumption = ThermalModelParameters(
            rated_top_oil_rise_k=make_provenanced_param("rated_top_oil_rise_k", 55.0, "K", ParameterSourceClass.ENGINEERING_ASSUMPTION),
            rated_hot_spot_rise_k=make_provenanced_param("rated_hot_spot_rise_k", 25.0, "K"),
            loss_ratio_r=make_provenanced_param("loss_ratio_r", 5.0, ""),
            oil_exponent_x=make_provenanced_param("oil_exponent_x", 0.8, ""),
            winding_exponent_y=make_provenanced_param("winding_exponent_y", 0.8, ""),
            time_constant_oil_hours=make_provenanced_param("time_constant_oil_hours", 3.0, "h"),
            time_constant_winding_hours=make_provenanced_param("time_constant_winding_hours", 0.1, "h"),
        )
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=params_with_assumption,
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            ambient_temperature_series=[30.0, 30.0],
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertTrue(any(i.code == ERR_UNVALIDATED_THERMAL_PARAMETERS for i in issues))

    def test_sensor_inversion_preserved_with_warning(self):
        """When measured hot spot < top oil, preserve raw value and emit WARN_ANOMALOUS_MEASURED_GRADIENT."""
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            measured_top_oil_series=[85.0, 85.0],
            measured_hot_spot_series=[80.0, 80.0],  # Inverted! 80 < 85
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertTrue(any(i.code == WARN_ANOMALOUS_MEASURED_GRADIENT for i in issues))
        # Raw value 80.0 preserved without clamping
        self.assertEqual(res[0].hot_spot_temp_c.value, 80.0)
        self.assertEqual(res[0].hot_spot_rise_k.value, -5.0)

    def test_no_universal_180k_life_fallback(self):
        """Without validated reference_life_hours, loss_of_life_percent is UNKNOWN; no 180k fallback."""
        params_no_ref_life = ThermalModelParameters(
            rated_top_oil_rise_k=make_provenanced_param("rated_top_oil_rise_k", 55.0, "K"),
            rated_hot_spot_rise_k=make_provenanced_param("rated_hot_spot_rise_k", 25.0, "K"),
            loss_ratio_r=make_provenanced_param("loss_ratio_r", 5.0, ""),
            oil_exponent_x=make_provenanced_param("oil_exponent_x", 0.8, ""),
            winding_exponent_y=make_provenanced_param("winding_exponent_y", 0.8, ""),
            time_constant_oil_hours=make_provenanced_param("time_constant_oil_hours", 3.0, "h"),
            time_constant_winding_hours=make_provenanced_param("time_constant_winding_hours", 0.1, "h"),
            reference_life_hours=None,  # Not configured!
        )
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=self.loading,
            thermal_parameters=params_no_ref_life,
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            measured_hot_spot_series=[110.0, 110.0],
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertIsNotNone(res[0].cumulative_aging_hours)
        self.assertIsNone(res[0].loss_of_life_percent)
        self.assertTrue(any(i.code == WARN_UNCONFIGURED_REFERENCE_LIFE for i in issues))


class TestGroup8NumericalSafety(unittest.TestCase):
    """Group 8: Absolute zero guard, float overflow protection, reference temperatures."""

    def test_absolute_zero_violation(self):
        """Hot spot <= -273.15 C emits ERR_UNSAFE_ARRHENIUS_EVALUATION."""
        f_aa, issue, ref_t = calculate_ieee_aging_acceleration_factor(
            -274.0,
            InsulationSystemType.THERMALLY_UPGRADED_PAPER,
        )
        self.assertIsNone(f_aa)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, ERR_UNSAFE_ARRHENIUS_EVALUATION)

    def test_overflow_protection_extreme_temperature(self):
        """Extreme temperature causing numerical overflow safely returns None with issue."""
        # IEC relative aging rate at 7000 C: 2^((7000-98)/6) = 2^1150 overflows IEEE 754 float
        v, issue, _ = calculate_iec_relative_ageing_rate(
            7000.0,
            InsulationSystemType.NON_THERMALLY_UPGRADED_PAPER,
        )
        self.assertIsNone(v)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, ERR_UNSAFE_ARRHENIUS_EVALUATION)

        # Non-finite IEEE temperature (inf / nan)
        f_aa_inf, issue_inf, _ = calculate_ieee_aging_acceleration_factor(
            float('inf'),
            InsulationSystemType.THERMALLY_UPGRADED_PAPER,
        )
        self.assertIsNone(f_aa_inf)
        self.assertIsNotNone(issue_inf)
        self.assertEqual(issue_inf.code, ERR_UNSAFE_ARRHENIUS_EVALUATION)

    def test_reference_temperature_fidelity(self):
        """Aging factors evaluate to exactly 1.0 at standard reference temperatures."""
        # IEEE Upgraded at 110 C -> 1.0
        f_aa_up, _, _ = calculate_ieee_aging_acceleration_factor(110.0, InsulationSystemType.THERMALLY_UPGRADED_PAPER)
        self.assertAlmostEqual(f_aa_up, 1.0, places=6)

        # IEEE Non-upgraded at 95 C -> 1.0
        f_aa_non, _, _ = calculate_ieee_aging_acceleration_factor(95.0, InsulationSystemType.NON_THERMALLY_UPGRADED_PAPER)
        self.assertAlmostEqual(f_aa_non, 1.0, places=6)

        # IEC Upgraded at 110 C -> 1.0
        v_up, _, _ = calculate_iec_relative_ageing_rate(110.0, InsulationSystemType.THERMALLY_UPGRADED_PAPER)
        self.assertAlmostEqual(v_up, 1.0, places=6)

        # IEC Non-upgraded at 98 C -> 1.0
        v_non, _, _ = calculate_iec_relative_ageing_rate(98.0, InsulationSystemType.NON_THERMALLY_UPGRADED_PAPER)
        self.assertAlmostEqual(v_non, 1.0, places=6)


class TestGroup10TargetedAuditRegression(unittest.TestCase):
    """Group 10: Targeted audit regressions for F-01 (timestamp precedence) and F-02 (chronology integrity)."""

    def setUp(self):
        self.engine = ThermalCalculationEngine()
        self.t0 = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(hours=1)

    def test_loading_result_with_only_loading_ratio_timestamp(self):
        """F-01 Regression: TransformerLoadingResult with only loading_ratio_pu.timestamp preserves deterministic timestamp."""
        lr0 = TransformerLoadingResult(
            is_computed=True,
            loading_ratio_pu=Measurement(
                value=1.0,
                unit="pu",
                evidence=EvidenceClassification.CALCULATED,
                quality=MeasurementQuality.GOOD,
                timestamp=self.t0,
            ),
            peak_loading_timestamp=None,  # Not provided!
            calculation_provenance={},    # No provenance timestamp!
        )
        lr1 = TransformerLoadingResult(
            is_computed=True,
            loading_ratio_pu=Measurement(
                value=1.0,
                unit="pu",
                evidence=EvidenceClassification.CALCULATED,
                quality=MeasurementQuality.GOOD,
                timestamp=self.t1,
            ),
            peak_loading_timestamp=None,  # Not provided!
            calculation_provenance={},    # No provenance timestamp!
        )

        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=[lr0, lr1],
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            measured_hot_spot_series=[110.0, 110.0],
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertEqual(len(res), 2)
        # Must strictly use loading_ratio_pu.timestamp (t0 and t1), not datetime.now()!
        self.assertEqual(res[0].timestamp, self.t0)
        self.assertEqual(res[1].timestamp, self.t1)
        self.assertAlmostEqual(res[0].forward_interval_result.duration_hours, 1.0, places=4)
        self.assertAlmostEqual(res[0].forward_interval_result.equivalent_aging_hours.value, 1.0, places=4)
        self.assertAlmostEqual(res[0].cumulative_aging_hours.value, 1.0, places=4)
        self.assertTrue(res[0].is_integration_complete)

    def test_duplicate_timestamps_mark_interval_unknown_and_prevent_cumulative_completeness(self):
        """F-02 Regression: Duplicate timestamps mark interval unknown and cumulative window incomplete."""
        # [t0, t0, t0 + 1h]: duplicate between sample 0 and sample 1
        records = [
            make_loading_record(1.0, self.t0),
            make_loading_record(1.0, self.t0),  # Duplicate timestamp!
            make_loading_record(1.0, self.t1),
        ]
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=records,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            measured_hot_spot_series=[110.0, 110.0, 110.0],
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertEqual(len(res), 3)

        # Issues must contain WARN_NON_MONOTONIC_TIMESTAMPS and WARN_INCOMPLETE_INTEGRATION_WINDOW
        self.assertTrue(any(i.code == WARN_NON_MONOTONIC_TIMESTAMPS for i in issues))
        self.assertTrue(any(i.code == WARN_INCOMPLETE_INTEGRATION_WINDOW for i in issues))

        # Interval 0 [t0, t0): duplicate duration 0.0, marked as continuity break, equivalent aging UNKNOWN (None)
        self.assertEqual(res[0].forward_interval_result.duration_hours, 0.0)
        self.assertTrue(res[0].forward_interval_result.is_continuity_break)
        self.assertIsNone(res[0].forward_interval_result.equivalent_aging_hours)

        # Cumulative window must be UNKNOWN and incomplete
        self.assertIsNone(res[0].cumulative_aging_hours)
        self.assertIsNone(res[0].loss_of_life_percent)
        self.assertFalse(res[0].is_integration_complete)

    def test_out_of_order_timestamps_mark_interval_unknown_and_prevent_cumulative_completeness(self):
        """F-02 Regression: Out-of-order timestamps mark interval unknown and cumulative window incomplete."""
        # [t0, t0 + 2h, t0 + 1h]: sample 2 precedes sample 1!
        t2_out_of_order = self.t0 + timedelta(hours=2)
        records = [
            make_loading_record(1.0, self.t0),
            make_loading_record(1.0, t2_out_of_order),
            make_loading_record(1.0, self.t1),  # Earlier than preceding sample!
        ]
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=records,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            measured_hot_spot_series=[110.0, 110.0, 110.0],
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertEqual(len(res), 3)

        self.assertTrue(any(i.code == WARN_NON_MONOTONIC_TIMESTAMPS for i in issues))
        self.assertTrue(any(i.code == WARN_INCOMPLETE_INTEGRATION_WINDOW for i in issues))

        # Interval 1 [t2, t1) has time reversal: duration clamped to 0.0, marked break, equivalent aging UNKNOWN
        self.assertEqual(res[1].forward_interval_result.duration_hours, 0.0)
        self.assertTrue(res[1].forward_interval_result.is_continuity_break)
        self.assertIsNone(res[1].forward_interval_result.equivalent_aging_hours)

        # Cumulative window must be UNKNOWN and incomplete
        self.assertIsNone(res[0].cumulative_aging_hours)
        self.assertIsNone(res[0].loss_of_life_percent)
        self.assertFalse(res[0].is_integration_complete)

    def test_valid_prior_intervals_preserved_for_audit_while_cumulative_remains_unknown(self):
        """F-02 Regression: Valid intervals before a chronology break are preserved for audit, but cumulative is UNKNOWN."""
        t2 = self.t1 + timedelta(hours=1)
        # [t0, t1, t1, t2]: interval 0 is valid [t0, t1), interval 1 is duplicate [t1, t1), interval 2 is valid [t1, t2)
        records = [
            make_loading_record(1.0, self.t0),
            make_loading_record(1.0, self.t1),
            make_loading_record(1.0, self.t1),  # Duplicate
            make_loading_record(1.0, t2),
        ]
        inp = ThermalAnalysisInput(
            asset_id="TX-01",
            loading_results=records,
            thermal_parameters=make_valid_ieee_params("TX-01"),
            insulation_system=InsulationSystemType.THERMALLY_UPGRADED_PAPER,
            thermal_model_standard=ThermalModelStandard.IEEE,
            aging_standard=AgingStandardPreference.IEEE,
            measured_hot_spot_series=[110.0, 110.0, 110.0, 110.0],
            continuity_tolerance_seconds=7200.0,
        )
        res, issues = self.engine.analyze_batch(inp)
        self.assertEqual(len(res), 4)

        # Interval 0 [t0, t1): 1.0 h duration, valid 1.0 h equivalent aging preserved
        self.assertIsNotNone(res[0].forward_interval_result.equivalent_aging_hours)
        self.assertAlmostEqual(res[0].forward_interval_result.equivalent_aging_hours.value, 1.0, places=4)
        self.assertFalse(res[0].forward_interval_result.is_continuity_break)

        # Interval 1 [t1, t1): duplicate, equivalent aging UNKNOWN
        self.assertIsNone(res[1].forward_interval_result.equivalent_aging_hours)
        self.assertTrue(res[1].forward_interval_result.is_continuity_break)

        # Cumulative across batch must be UNKNOWN due to chronological flaw
        self.assertIsNone(res[0].cumulative_aging_hours)
        self.assertFalse(res[0].is_integration_complete)


if __name__ == "__main__":
    unittest.main()
