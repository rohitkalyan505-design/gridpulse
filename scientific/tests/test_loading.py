"""
GridPulse — Phase 2 Step 4 Transformer Loading & Overload Analytics Tests

Comprehensive unit tests verifying:
A. Contract:
   - No phase-loading fields in TransformerLoadingResult.
   - Serialization contains no phase-loading fields.
B. Thresholds:
   - Equal thresholds rejected.
   - Inverted thresholds rejected.
   - Non-positive thresholds rejected.
   - NaN / Infinity rejected.
   - continuous_threshold < 0.80 rejected.
   - continuous_threshold = 0.80 accepted.
   - Valid threshold combinations accepted.
   - Preservation of invalid configuration in diagnostic issue.
C. Loading mathematics:
   - Canonical kVA conversion (VA, kVA, MVA).
   - Loading ratio (L = S_actual / S_rated).
   - Loading percentage (L% = L * 100).
   - Deterministic screening-band classifications (LIGHT, NORMAL, ELEVATED, CONTINUOUS_OVERLOAD, EMERGENCY_OVERLOAD).
D. Forward interval methodology:
   - (t0, 0.50), (t1, 0.70), (t2, 0.90) with delta_t = 300s -> strictly 0.60 pu, NOT 0.70 pu (no trapezoidal interpolation).
   - First sample determines forward interval [t_k, t_{k+1}).
E. Final sample:
   - Changing final sample from 0.90 to 1.50 does not change average (final delta_t = 0).
F. Continuity & Data Quality:
   - Missing, invalid, BAD, OUT_OF_RANGE quality, and gap > max_gap break continuity without bridging.
G. Overload cycles:
   - Start, normal termination, continuous-overload vs emergency-overload classification.
   - Continuity-break termination and WARN_TELEMETRY_CONTINUITY_BREAK emission without speculative bridging.
H. Peak loading:
   - Invalid/unusable records excluded from peak.
   - Peak timestamp and apparent power captured accurately.
I. Evidence classification:
   - All derived loading metrics carry EvidenceClassification.CALCULATED.
J. Provenance:
   - Mandatory 1.4 pu qualification clause preserved verbatim.
   - Provenance records formula ID, equation, inputs, and thresholds.
"""

from datetime import datetime, timedelta, timezone
import math
import unittest

from scientific.contracts.asset import (
    OperationalLimits,
    TransformerAssetSpec,
    validate_loading_thresholds,
)
from scientific.contracts.enums import (
    CoolingType,
    EvidenceClassification,
    InsulationClass,
    IssueSeverity,
    LoadingState,
    MeasurementQuality,
    OverloadSeverity,
    WindingMaterial,
)
from scientific.contracts.measurement import Measurement
from scientific.contracts.results import (
    ElectricalFeaturesResult,
    OverloadCycle,
    TransformerLoadingResult,
)
from scientific.features.engine import ElectricalCalculationEngine
from scientific.features.loading import (
    CLASSIFICATION_SCREENING_CONVENTIONS,
    DEFAULT_EMERGENCY_SCREENING_QUALIFICATION,
    calculate_batch_loading,
    calculate_record_loading,
    classify_loading_state,
    normalize_apparent_power_to_canonical_kva,
)


def create_test_asset(
    asset_id: str = "TX-TEST-001",
    rated_power_kva: float = 500.0,
    max_continuous_loading_pu: float = 1.0,
    emergency_loading_pu: float = 1.4,
) -> TransformerAssetSpec:
    """Helper to instantiate a standard transformer asset specification."""
    return TransformerAssetSpec(
        asset_id=asset_id,
        rated_power_kva=rated_power_kva,
        primary_voltage_v=11000.0,
        secondary_voltage_v=433.0,
        rated_frequency_hz=50.0,
        phases=3,
        cooling_type=CoolingType.ONAN,
        winding_material=WindingMaterial.COPPER,
        insulation_class=InsulationClass.CLASS_A_105,
        operational_limits=OperationalLimits(
            max_continuous_loading_pu=max_continuous_loading_pu,
            emergency_loading_pu=emergency_loading_pu,
        ),
    )


def make_apparent_power_measurement(
    value: float,
    unit: str = "kVA",
    quality: MeasurementQuality = MeasurementQuality.GOOD,
    timestamp: datetime = None,
    evidence: EvidenceClassification = EvidenceClassification.CALCULATED,
) -> Measurement[float]:
    """Helper to construct a valid apparent power Measurement object."""
    ts = timestamp or datetime.now(timezone.utc)
    if quality == MeasurementQuality.MISSING:
        return Measurement.create_missing(unit, ts)
    return Measurement(
        value=value,
        unit=unit,
        evidence=evidence,
        quality=quality,
        timestamp=ts,
    )


def make_features_result(
    apparent_power: Measurement[float],
) -> ElectricalFeaturesResult:
    """Helper to wrap an apparent power measurement into an ElectricalFeaturesResult."""
    return ElectricalFeaturesResult(
        is_computed=True,
        apparent_power_kva=apparent_power,
    )


class TestTransformerLoadingContracts(unittest.TestCase):
    """A. Contract verification: Zero per-phase loading fields."""

    def test_no_phase_loading_fields_in_result(self):
        tl = TransformerLoadingResult()
        self.assertFalse(hasattr(tl, "phase_a_loading_pu"))
        self.assertFalse(hasattr(tl, "phase_b_loading_pu"))
        self.assertFalse(hasattr(tl, "phase_c_loading_pu"))

    def test_overload_cycle_contract(self):
        now = datetime.now(timezone.utc)
        cycle = OverloadCycle(
            cycle_id="OLC-001",
            start_time=now,
            end_time=now + timedelta(seconds=600),
            duration_seconds=600.0,
            peak_loading_ratio_pu=1.25,
            peak_apparent_power_kva=625.0,
            severity=OverloadSeverity.CONTINUOUS_OVERLOAD,
            continuity_break_detected=False,
        )
        d = cycle.to_dict()
        self.assertEqual(d["cycle_id"], "OLC-001")
        self.assertEqual(d["duration_seconds"], 600.0)
        self.assertEqual(d["severity"], "CONTINUOUS_OVERLOAD")
        self.assertFalse(d["continuity_break_detected"])


class TestLoadingThresholdValidation(unittest.TestCase):
    """B. Threshold invariants: 0.80 <= continuous < emergency, finite, positive."""

    def test_valid_threshold_combinations_accepted(self):
        # Baseline standard
        valid, issue = validate_loading_thresholds(1.0, 1.4)
        self.assertTrue(valid)
        self.assertIsNone(issue)

        # Exact lower boundary: continuous = 0.80
        valid, issue = validate_loading_thresholds(0.80, 1.10)
        self.assertTrue(valid)
        self.assertIsNone(issue)

        # High rating
        valid, issue = validate_loading_thresholds(1.20, 1.60)
        self.assertTrue(valid)
        self.assertIsNone(issue)

    def test_equal_thresholds_rejected(self):
        valid, issue = validate_loading_thresholds(1.0, 1.0)
        self.assertFalse(valid)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.code, "ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION")
        self.assertEqual(issue.severity, IssueSeverity.CRITICAL)

    def test_inverted_thresholds_rejected(self):
        valid, issue = validate_loading_thresholds(1.2, 1.0)
        self.assertFalse(valid)
        self.assertEqual(issue.code, "ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION")

    def test_continuous_threshold_below_screening_lower_bound_rejected(self):
        # 0.79 is below 0.80
        valid, issue = validate_loading_thresholds(0.79, 1.20)
        self.assertFalse(valid)
        self.assertEqual(issue.code, "ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION")
        self.assertIn("0.80", issue.message)

    def test_non_positive_thresholds_rejected(self):
        valid, issue = validate_loading_thresholds(0.0, 1.4)
        self.assertFalse(valid)
        self.assertEqual(issue.code, "ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION")

        valid, issue = validate_loading_thresholds(-0.5, 1.4)
        self.assertFalse(valid)
        self.assertEqual(issue.code, "ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION")

        valid, issue = validate_loading_thresholds(1.0, 0.0)
        self.assertFalse(valid)
        self.assertEqual(issue.code, "ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION")

    def test_nan_thresholds_rejected(self):
        valid, issue = validate_loading_thresholds(float("nan"), 1.4)
        self.assertFalse(valid)
        self.assertEqual(issue.code, "ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION")

        valid, issue = validate_loading_thresholds(1.0, float("nan"))
        self.assertFalse(valid)
        self.assertEqual(issue.code, "ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION")

    def test_infinity_thresholds_rejected(self):
        valid, issue = validate_loading_thresholds(float("inf"), 1.4)
        self.assertFalse(valid)
        self.assertEqual(issue.code, "ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION")

        valid, issue = validate_loading_thresholds(1.0, float("inf"))
        self.assertFalse(valid)
        self.assertEqual(issue.code, "ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION")

    def test_invalid_thresholds_halt_calculation_and_preserve_config(self):
        asset = create_test_asset(max_continuous_loading_pu=0.75, emergency_loading_pu=1.4)
        s_meas = make_apparent_power_measurement(400.0)
        res, issues = calculate_record_loading(s_meas, asset)
        self.assertIsNone(res)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].code, "ERR_INVALID_LOADING_THRESHOLD_CONFIGURATION")
        self.assertIn("0.75", issues[0].message)


class TestLoadingMathematics(unittest.TestCase):
    """C. Loading ratios, canonical kVA, and screening bands."""

    def setUp(self):
        self.asset = create_test_asset(rated_power_kva=500.0)

    def test_canonical_kva_conversion(self):
        # VA -> kVA
        m_va = make_apparent_power_measurement(250000.0, unit="VA")
        val_kva, issue = normalize_apparent_power_to_canonical_kva(m_va)
        self.assertIsNone(issue)
        self.assertAlmostEqual(val_kva, 250.0)

        # MVA -> kVA
        m_mva = make_apparent_power_measurement(0.25, unit="MVA")
        val_kva, issue = normalize_apparent_power_to_canonical_kva(m_mva)
        self.assertIsNone(issue)
        self.assertAlmostEqual(val_kva, 250.0)

        # kVA -> kVA
        m_kva = make_apparent_power_measurement(250.0, unit="kVA")
        val_kva, issue = normalize_apparent_power_to_canonical_kva(m_kva)
        self.assertIsNone(issue)
        self.assertAlmostEqual(val_kva, 250.0)

    def test_loading_ratio_and_percentage(self):
        m_s = make_apparent_power_measurement(250.0, unit="kVA")
        res, issues = calculate_record_loading(m_s, self.asset)
        self.assertEqual(len(issues), 0)
        self.assertIsNotNone(res)
        self.assertTrue(res.is_computed)
        self.assertAlmostEqual(res.loading_ratio_pu.value, 0.50)
        self.assertAlmostEqual(res.loading_percent.value, 50.0)
        self.assertEqual(res.loading_state, LoadingState.NORMAL)
        self.assertFalse(res.is_overloaded)
        self.assertFalse(res.is_emergency)

    def test_screening_band_boundaries(self):
        cont = 1.0
        emerg = 1.4

        # LIGHT: 0.00 <= L < 0.30
        self.assertEqual(classify_loading_state(0.00, cont, emerg), LoadingState.LIGHT)
        self.assertEqual(classify_loading_state(0.2999, cont, emerg), LoadingState.LIGHT)

        # NORMAL: 0.30 <= L <= 0.80
        self.assertEqual(classify_loading_state(0.30, cont, emerg), LoadingState.NORMAL)
        self.assertEqual(classify_loading_state(0.55, cont, emerg), LoadingState.NORMAL)
        self.assertEqual(classify_loading_state(0.80, cont, emerg), LoadingState.NORMAL)

        # ELEVATED: 0.80 < L <= continuous_threshold
        self.assertEqual(classify_loading_state(0.8001, cont, emerg), LoadingState.ELEVATED)
        self.assertEqual(classify_loading_state(0.95, cont, emerg), LoadingState.ELEVATED)
        self.assertEqual(classify_loading_state(1.00, cont, emerg), LoadingState.ELEVATED)

        # CONTINUOUS_OVERLOAD: continuous_threshold < L <= emergency_threshold
        self.assertEqual(classify_loading_state(1.0001, cont, emerg), LoadingState.CONTINUOUS_OVERLOAD)
        self.assertEqual(classify_loading_state(1.20, cont, emerg), LoadingState.CONTINUOUS_OVERLOAD)
        self.assertEqual(classify_loading_state(1.40, cont, emerg), LoadingState.CONTINUOUS_OVERLOAD)

        # EMERGENCY_OVERLOAD: L > emergency_threshold
        self.assertEqual(classify_loading_state(1.4001, cont, emerg), LoadingState.EMERGENCY_OVERLOAD)
        self.assertEqual(classify_loading_state(2.00, cont, emerg), LoadingState.EMERGENCY_OVERLOAD)

    def test_non_positive_rated_power_rejected(self):
        # 1. Spec creation level rejection
        with self.assertRaises(ValueError):
            create_test_asset(rated_power_kva=-10.0)
        with self.assertRaises(ValueError):
            create_test_asset(rated_power_kva=0.0)

        # 2. Calculation engine level rejection and diagnostic issue
        dummy_asset = create_test_asset(rated_power_kva=100.0)
        object.__setattr__(dummy_asset, "rated_power_kva", -10.0)
        m_s = make_apparent_power_measurement(250.0)
        res, issues = calculate_record_loading(m_s, dummy_asset)
        self.assertIsNone(res)
        self.assertEqual(issues[0].code, "ERR_NON_POSITIVE_RATED_CAPACITY")

        object.__setattr__(dummy_asset, "rated_power_kva", 0.0)
        res_zero, issues_zero = calculate_record_loading(m_s, dummy_asset)
        self.assertIsNone(res_zero)
        self.assertEqual(issues_zero[0].code, "ERR_NON_POSITIVE_RATED_CAPACITY")


    def test_non_finite_apparent_power_rejected(self):
        m_nan = make_apparent_power_measurement(float("nan"))
        res, issues = calculate_record_loading(m_nan, self.asset)
        self.assertIsNone(res)
        self.assertEqual(issues[0].code, "ERR_NON_FINITE_INPUT")

        m_inf = make_apparent_power_measurement(float("inf"))
        res, issues = calculate_record_loading(m_inf, self.asset)
        self.assertIsNone(res)
        self.assertEqual(issues[0].code, "ERR_NON_FINITE_INPUT")


class TestForwardIntervalMethodology(unittest.TestCase):
    """D & E. Forward-interval sample-and-hold time-weighted average (zero interpolation)."""

    def setUp(self):
        self.asset = create_test_asset(rated_power_kva=100.0)
        self.t0 = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(seconds=300)
        self.t2 = self.t1 + timedelta(seconds=300)

    def test_approved_forward_interval_mathematics(self):
        """
        Verify:
        (t0, 0.50 pu) -> 50 kVA
        (t1, 0.70 pu) -> 70 kVA
        (t2, 0.90 pu) -> 90 kVA
        delta_t0 = 300 s, delta_t1 = 300 s.
        Expected: (0.50*300 + 0.70*300) / 600 = 0.60 pu.
        Trapezoidal would have produced: ((0.50+0.70)/2*300 + (0.70+0.90)/2*300)/600 = 0.70 pu.
        Assert that result is strictly 0.60 and NOT 0.70.
        """
        feats = [
            make_features_result(make_apparent_power_measurement(50.0, timestamp=self.t0)),
            make_features_result(make_apparent_power_measurement(70.0, timestamp=self.t1)),
            make_features_result(make_apparent_power_measurement(90.0, timestamp=self.t2)),
        ]
        res, issues = calculate_batch_loading(feats, self.asset, nominal_interval_seconds=300.0)
        self.assertEqual(len(issues), 0)
        self.assertIsNotNone(res.time_weighted_average_loading_pu)

        actual_avg = res.time_weighted_average_loading_pu.value
        self.assertAlmostEqual(actual_avg, 0.60, places=5)
        self.assertNotAlmostEqual(actual_avg, 0.70, places=3)  # Proves NO trapezoidal interpolation

    def test_final_sample_zero_duration_contribution(self):
        """
        Changing final sample L2 from 90 kVA (0.90 pu) to 150 kVA (1.50 pu)
        must NOT change the time-weighted average over [t0, t2), because
        final sample has delta_t = 0.
        """
        feats_initial = [
            make_features_result(make_apparent_power_measurement(50.0, timestamp=self.t0)),
            make_features_result(make_apparent_power_measurement(70.0, timestamp=self.t1)),
            make_features_result(make_apparent_power_measurement(90.0, timestamp=self.t2)),
        ]
        res_initial, _ = calculate_batch_loading(feats_initial, self.asset)

        feats_modified_final = [
            make_features_result(make_apparent_power_measurement(50.0, timestamp=self.t0)),
            make_features_result(make_apparent_power_measurement(70.0, timestamp=self.t1)),
            make_features_result(make_apparent_power_measurement(150.0, timestamp=self.t2)),
        ]
        res_modified, _ = calculate_batch_loading(feats_modified_final, self.asset)

        self.assertAlmostEqual(
            res_initial.time_weighted_average_loading_pu.value,
            res_modified.time_weighted_average_loading_pu.value,
            places=5,
        )
        self.assertAlmostEqual(res_modified.time_weighted_average_loading_pu.value, 0.60, places=5)

    def test_first_sample_determines_following_interval(self):
        """Verify that L0 governs the entire interval [t0, t1)."""
        feats = [
            make_features_result(make_apparent_power_measurement(30.0, timestamp=self.t0)),  # 0.30 pu
            make_features_result(make_apparent_power_measurement(80.0, timestamp=self.t1)),  # 0.80 pu
        ]
        res, _ = calculate_batch_loading(feats, self.asset)
        # Duration is 300s (from t0 to t1), governed by L0 (0.30 pu)
        self.assertAlmostEqual(res.time_weighted_average_loading_pu.value, 0.30, places=5)


class TestContinuityAndDataQuality(unittest.TestCase):
    """F. Quality filtering and continuity break detection."""

    def setUp(self):
        self.asset = create_test_asset(rated_power_kva=100.0)
        self.t0 = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(seconds=300)
        self.t2 = self.t1 + timedelta(seconds=300)
        self.t3 = self.t2 + timedelta(seconds=300)

    def test_bad_quality_breaks_continuity(self):
        """
        t0 (50 kVA, GOOD) -> t1 (70 kVA, BAD) -> t2 (80 kVA, GOOD)
        Must NOT bridge t0 directly to t2.
        [t0, t1) is invalid because t1 is BAD.
        [t1, t2) is invalid because t1 is BAD.
        Total valid duration is 0, average is None.
        """
        feats = [
            make_features_result(make_apparent_power_measurement(50.0, timestamp=self.t0)),
            make_features_result(
                make_apparent_power_measurement(70.0, quality=MeasurementQuality.BAD, timestamp=self.t1)
            ),
            make_features_result(make_apparent_power_measurement(80.0, timestamp=self.t2)),
        ]
        res, _ = calculate_batch_loading(feats, self.asset)
        self.assertIsNone(res.time_weighted_average_loading_pu)

    def test_missing_quality_breaks_continuity(self):
        """Missing quality prevents interval accumulation."""
        feats = [
            make_features_result(make_apparent_power_measurement(50.0, timestamp=self.t0)),
            make_features_result(
                make_apparent_power_measurement(None, quality=MeasurementQuality.MISSING, timestamp=self.t1)
            ),
            make_features_result(make_apparent_power_measurement(80.0, timestamp=self.t2)),
            make_features_result(make_apparent_power_measurement(90.0, timestamp=self.t3)),
        ]
        res, _ = calculate_batch_loading(feats, self.asset)
        # Only [t2, t3) is valid: duration 300s, governed by L2 (80 kVA = 0.80 pu)
        self.assertIsNotNone(res.time_weighted_average_loading_pu)
        self.assertAlmostEqual(res.time_weighted_average_loading_pu.value, 0.80, places=5)

    def test_out_of_range_breaks_continuity(self):
        feats = [
            make_features_result(make_apparent_power_measurement(50.0, timestamp=self.t0)),
            make_features_result(
                make_apparent_power_measurement(500.0, quality=MeasurementQuality.OUT_OF_RANGE, timestamp=self.t1)
            ),
            make_features_result(make_apparent_power_measurement(60.0, timestamp=self.t2)),
        ]
        res, _ = calculate_batch_loading(feats, self.asset)
        self.assertIsNone(res.time_weighted_average_loading_pu)

    def test_gap_exceeding_max_gap_excluded(self):
        """Telemetry gap > 2 * nominal_interval_seconds (600s) is excluded."""
        t_gap = self.t0 + timedelta(seconds=1200)  # Gap of 1200s > 600s
        feats = [
            make_features_result(make_apparent_power_measurement(50.0, timestamp=self.t0)),
            make_features_result(make_apparent_power_measurement(60.0, timestamp=t_gap)),
        ]
        res, _ = calculate_batch_loading(feats, self.asset, nominal_interval_seconds=300.0)
        self.assertIsNone(res.time_weighted_average_loading_pu)


class TestOverloadCycles(unittest.TestCase):
    """G. Deterministic overload cycles and continuity break termination."""

    def setUp(self):
        self.asset = create_test_asset(
            rated_power_kva=100.0,
            max_continuous_loading_pu=1.0,
            emergency_loading_pu=1.4,
        )
        self.t0 = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(seconds=300)
        self.t2 = self.t1 + timedelta(seconds=300)
        self.t3 = self.t2 + timedelta(seconds=300)

    def test_continuous_overload_cycle_start_and_normal_termination(self):
        """
        t0: 80 kVA (0.80 pu, normal)
        t1: 120 kVA (1.20 pu, overload) -> starts cycle
        t2: 130 kVA (1.30 pu, overload) -> continues cycle
        t3: 90 kVA (0.90 pu, normal)   -> normal termination
        Cycle duration: [t1, t2) + [t2, t3) = 600 s.
        Severity: CONTINUOUS_OVERLOAD (peak 1.30 <= 1.40).
        """
        feats = [
            make_features_result(make_apparent_power_measurement(80.0, timestamp=self.t0)),
            make_features_result(make_apparent_power_measurement(120.0, timestamp=self.t1)),
            make_features_result(make_apparent_power_measurement(130.0, timestamp=self.t2)),
            make_features_result(make_apparent_power_measurement(90.0, timestamp=self.t3)),
        ]
        res, _ = calculate_batch_loading(feats, self.asset)
        self.assertTrue(res.is_overloaded)
        self.assertFalse(res.is_emergency)
        self.assertEqual(len(res.overload_cycles), 1)

        c = res.overload_cycles[0]
        self.assertEqual(c.start_time, self.t1)
        self.assertEqual(c.end_time, self.t3)
        self.assertEqual(c.duration_seconds, 600.0)
        self.assertAlmostEqual(c.peak_loading_ratio_pu, 1.30)
        self.assertEqual(c.severity, OverloadSeverity.CONTINUOUS_OVERLOAD)
        self.assertFalse(c.continuity_break_detected)

    def test_emergency_overload_cycle_classification(self):
        """Peak loading > 1.40 pu classifies cycle as EMERGENCY_OVERLOAD."""
        feats = [
            make_features_result(make_apparent_power_measurement(80.0, timestamp=self.t0)),
            make_features_result(make_apparent_power_measurement(150.0, timestamp=self.t1)),  # 1.50 pu > 1.40
            make_features_result(make_apparent_power_measurement(90.0, timestamp=self.t2)),
        ]
        res, _ = calculate_batch_loading(feats, self.asset)
        self.assertTrue(res.is_overloaded)
        self.assertTrue(res.is_emergency)
        self.assertEqual(len(res.overload_cycles), 1)
        self.assertEqual(res.overload_cycles[0].severity, OverloadSeverity.EMERGENCY_OVERLOAD)

    def test_overload_continuity_break_termination(self):
        """
        Active overload at t1 (1.20 pu).
        t2 is BAD quality.
        The cycle must terminate immediately at t1, continuity_break_detected=True,
        and emit WARN_TELEMETRY_CONTINUITY_BREAK without bridging.
        """
        feats = [
            make_features_result(make_apparent_power_measurement(80.0, timestamp=self.t0)),
            make_features_result(make_apparent_power_measurement(120.0, timestamp=self.t1)),
            make_features_result(
                make_apparent_power_measurement(120.0, quality=MeasurementQuality.BAD, timestamp=self.t2)
            ),
            make_features_result(make_apparent_power_measurement(90.0, timestamp=self.t3)),
        ]
        res, issues = calculate_batch_loading(feats, self.asset)
        self.assertEqual(len(res.overload_cycles), 1)
        c = res.overload_cycles[0]
        self.assertEqual(c.start_time, self.t1)
        self.assertEqual(c.end_time, self.t1)  # Terminated at last valid observed overloaded ts
        self.assertEqual(c.duration_seconds, 0.0)
        self.assertTrue(c.continuity_break_detected)

        break_issues = [i for i in issues if i.code == "WARN_TELEMETRY_CONTINUITY_BREAK"]
        self.assertEqual(len(break_issues), 1)
        self.assertEqual(break_issues[0].severity, IssueSeverity.WARNING)


class TestPeakLoading(unittest.TestCase):
    """H. Peak loading observation rules."""

    def setUp(self):
        self.asset = create_test_asset(rated_power_kva=100.0)
        self.t0 = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(seconds=300)
        self.t2 = self.t1 + timedelta(seconds=300)

    def test_invalid_records_cannot_become_peak(self):
        """A BAD record with 500 kVA must be ignored; peak must be 85 kVA (0.85 pu)."""
        feats = [
            make_features_result(make_apparent_power_measurement(40.0, timestamp=self.t0)),
            make_features_result(
                make_apparent_power_measurement(500.0, quality=MeasurementQuality.BAD, timestamp=self.t1)
            ),
            make_features_result(make_apparent_power_measurement(85.0, timestamp=self.t2)),
        ]
        res, _ = calculate_batch_loading(feats, self.asset)
        self.assertIsNotNone(res.peak_loading_ratio_pu)
        self.assertAlmostEqual(res.peak_loading_ratio_pu.value, 0.85)
        self.assertEqual(res.peak_loading_timestamp, self.t2)


class TestEvidenceAndProvenance(unittest.TestCase):
    """I & J. Evidence classification and provenance qualification verification."""

    def setUp(self):
        self.asset = create_test_asset(rated_power_kva=100.0)
        self.t0 = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
        self.t1 = self.t0 + timedelta(seconds=300)

    def test_all_derived_metrics_carry_calculated_evidence(self):
        feats = [
            make_features_result(make_apparent_power_measurement(50.0, timestamp=self.t0)),
            make_features_result(make_apparent_power_measurement(70.0, timestamp=self.t1)),
        ]
        res, _ = calculate_batch_loading(feats, self.asset)
        self.assertEqual(res.loading_ratio_pu.evidence, EvidenceClassification.CALCULATED)
        self.assertEqual(res.loading_percent.evidence, EvidenceClassification.CALCULATED)
        self.assertEqual(res.time_weighted_average_loading_pu.evidence, EvidenceClassification.CALCULATED)
        self.assertEqual(res.peak_loading_ratio_pu.evidence, EvidenceClassification.CALCULATED)

    def test_provenance_contains_qualification_clause(self):
        m_s = make_apparent_power_measurement(75.0, timestamp=self.t0)
        res, _ = calculate_record_loading(m_s, self.asset)
        prov = res.calculation_provenance
        self.assertIn("emergency_threshold_qualification", prov)
        self.assertEqual(
            prov["emergency_threshold_qualification"],
            DEFAULT_EMERGENCY_SCREENING_QUALIFICATION,
        )
        self.assertIn(
            "1.4 pu is the GridPulse default screening convention when no asset-specific emergency threshold is configured.",
            prov["emergency_threshold_qualification"],
        )


class TestElectricalCalculationEngineIntegration(unittest.TestCase):
    """Engine integration tests for record and batch loading methods."""

    def test_engine_compute_loading(self):
        asset = create_test_asset(rated_power_kva=200.0)
        engine = ElectricalCalculationEngine(asset_spec=asset)
        m_s = make_apparent_power_measurement(100.0)
        feat = make_features_result(m_s)

        res, issues = engine.compute_record_loading(feat)
        self.assertEqual(len(issues), 0)
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res.loading_ratio_pu.value, 0.50)

        batch_res, batch_issues = engine.compute_batch_loading([feat])
        self.assertEqual(len(batch_issues), 0)
        self.assertTrue(batch_res.is_computed)


if __name__ == "__main__":
    unittest.main()
