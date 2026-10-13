"""
GridPulse — Phase Imbalance, Symmetrical Components & Derating Tests
Comprehensive test suite verifying Phase 2 Step 6 scientific requirements:
- Group 1: Phase Magnitude Imbalance (Voltage & Current)
- Group 2: Fortescue Symmetrical Components (Complex Phasors, Reconstruction, Sequence Ratios)
- Group 3: Angle Absence, Magnitude-Only Guard, and Sequence Conventions
- Group 4: Numerical Safety, Near-Zero Denominator, and Boundary Conditions
- Group 5: Evidence Classification, Data Quality & Timestamp Integrity
- Group 6: Evidence-Grounded Transformer Derating Analytics
- Group 7: PhaseImbalanceEngine End-to-End Pipeline Integration
"""

import cmath
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, List, Optional, Tuple
import unittest


from scientific.contracts.asset import OperationalLimits, TransformerAssetSpec
from scientific.contracts.enums import (
    CoolingType,
    DeratingMethod,
    EvidenceClassification,
    InsulationClass,
    IssueSeverity,
    MeasurementQuality,
    PhaseIdentification,
    PhaseSequence,
    PhasorAngleConvention,
    WindingMaterial,
)
from scientific.contracts.issues import (
    ERR_DEGENERATE_POSITIVE_SEQUENCE,
    ERR_INCOMPLETE_THREE_PHASE_TELEMETRY,
    ERR_MISMATCHED_PHASE_TIMESTAMPS,
    ERR_MISSING_PHASOR_ANGLES,
    WARN_CURRENT_UNBALANCE_EXCEEDS_LIMIT,
    WARN_DERATING_METHOD_UNAVAILABLE,
    WARN_UNVERIFIED_DERATING_PARAMETERS,
    WARN_VOLTAGE_UNBALANCE_EXCEEDS_LIMIT,
    WARN_ZERO_MEAN_MAGNITUDE,
)
from scientific.contracts.measurement import Measurement
from scientific.contracts.results import (
    ElectricalFeaturesResult,
    PhaseImbalanceResult,
    TransformerLoadingResult,
)
from scientific.imbalance.calculations import (
    calculate_phase_magnitude_imbalance,
    calculate_symmetrical_components,
    calculate_transformer_derating,
)
from scientific.imbalance.contracts import (
    ComplexPhasor,
    DeratingAssessmentResult,
    DeratingConfiguration,
    PhaseImbalanceInput,
    PhaseMagnitudeImbalance,
    PhaseQuantity,
    SymmetricalComponentsResult,
    ThreePhaseQuantity,
)
from scientific.imbalance.engine import PhaseImbalanceEngine


def make_meas(
    val: float,
    unit: str = "V",
    evidence: EvidenceClassification = EvidenceClassification.MEASURED,
    quality: MeasurementQuality = MeasurementQuality.GOOD,
    ts: Optional[datetime] = None,
) -> Measurement[float]:
    """Helper to construct a valid Measurement."""
    timestamp = ts or datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
    return Measurement(
        value=val,
        unit=unit,
        evidence=evidence,
        quality=quality,
        timestamp=timestamp,
    )


def make_spec(asset_id: str = "TX-TEST-001") -> TransformerAssetSpec:
    """Helper to construct a standard TransformerAssetSpec."""
    return TransformerAssetSpec(
        asset_id=asset_id,
        rated_power_kva=1000.0,
        primary_voltage_v=11000.0,
        secondary_voltage_v=415.0,
        rated_frequency_hz=50.0,
        phases=3,
        cooling_type=CoolingType.ONAN,
        winding_material=WindingMaterial.COPPER,
        insulation_class=InsulationClass.CLASS_A_105,
        operational_limits=OperationalLimits(
            max_voltage_unbalance_percent=2.0,
            max_current_unbalance_percent=10.0,
        ),
    )


class TestGroup1MagnitudeImbalance(unittest.TestCase):
    """
    Tests for Category A: Phase Magnitude Imbalance formulations (PVUR, CMUR).
    Verifies mean, signed deviations, absolute deviations, and percentage unbalance.
    """

    def setUp(self) -> None:
        self.ts = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    def test_three_equal_phase_magnitudes_balanced(self) -> None:
        """Balanced three-phase system must yield 0 deviations and 0% unbalance."""
        tp = ThreePhaseQuantity.from_measurements(
            va=make_meas(230.0, "V", ts=self.ts),
            vb=make_meas(230.0, "V", ts=self.ts),
            vc=make_meas(230.0, "V", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        res, issues = calculate_phase_magnitude_imbalance(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        self.assertEqual(len(issues), 0)
        self.assertAlmostEqual(res.mean_magnitude.value, 230.0, places=6)
        self.assertAlmostEqual(res.max_absolute_deviation.value, 0.0, places=6)
        self.assertIsNotNone(res.max_deviation_percent)
        self.assertAlmostEqual(res.max_deviation_percent.value, 0.0, places=6)
        self.assertEqual(res.max_deviation_percent.unit, "percent")

    def test_one_elevated_phase(self) -> None:
        """One elevated phase: Va=250V, Vb=225V, Vc=225V -> Mean=233.333V, max dev = |250 - 233.333| = 16.667V."""
        tp = ThreePhaseQuantity.from_measurements(
            va=make_meas(250.0, "V", ts=self.ts),
            vb=make_meas(225.0, "V", ts=self.ts),
            vc=make_meas(225.0, "V", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        res, issues = calculate_phase_magnitude_imbalance(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        self.assertEqual(len(issues), 0)
        expected_mean = (250.0 + 225.0 + 225.0) / 3.0
        expected_max_dev = 250.0 - expected_mean
        expected_pct = (expected_max_dev / expected_mean) * 100.0

        self.assertAlmostEqual(res.mean_magnitude.value, expected_mean, places=6)
        self.assertAlmostEqual(res.deviations_signed["A"].value, expected_max_dev, places=6)
        self.assertAlmostEqual(res.max_absolute_deviation.value, expected_max_dev, places=6)
        self.assertAlmostEqual(res.max_deviation_percent.value, expected_pct, places=6)

    def test_one_reduced_phase(self) -> None:
        """One depressed phase: Va=200V, Vb=230V, Vc=230V -> Mean=220V, max dev = |200-220| = 20V."""
        tp = ThreePhaseQuantity.from_measurements(
            va=make_meas(200.0, "V", ts=self.ts),
            vb=make_meas(230.0, "V", ts=self.ts),
            vc=make_meas(230.0, "V", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        res, issues = calculate_phase_magnitude_imbalance(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res.mean_magnitude.value, 220.0, places=6)
        self.assertAlmostEqual(res.deviations_signed["A"].value, -20.0, places=6)
        self.assertAlmostEqual(res.deviations_absolute["A"].value, 20.0, places=6)
        self.assertAlmostEqual(res.max_absolute_deviation.value, 20.0, places=6)
        self.assertAlmostEqual(res.max_deviation_percent.value, (20.0 / 220.0) * 100.0, places=6)

    def test_all_three_phases_unequal(self) -> None:
        """All three phases unequal: 240, 220, 200 V -> Mean=220V, max dev=20V (both A and C)."""
        tp = ThreePhaseQuantity.from_measurements(
            va=make_meas(240.0, "V", ts=self.ts),
            vb=make_meas(220.0, "V", ts=self.ts),
            vc=make_meas(200.0, "V", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        res, issues = calculate_phase_magnitude_imbalance(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res.mean_magnitude.value, 220.0, places=6)
        self.assertAlmostEqual(res.max_absolute_deviation.value, 20.0, places=6)
        self.assertAlmostEqual(res.max_deviation_percent.value, (20.0 / 220.0) * 100.0, places=6)

    def test_zero_mean_degenerate_inputs_avoids_zero_division(self) -> None:
        """All zeros (0V, 0V, 0V): Mean=0V. Must return UNKNOWN for percent and emit WARN_ZERO_MEAN_MAGNITUDE."""
        tp = ThreePhaseQuantity.from_measurements(
            va=make_meas(0.0, "V", ts=self.ts),
            vb=make_meas(0.0, "V", ts=self.ts),
            vc=make_meas(0.0, "V", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        res, issues = calculate_phase_magnitude_imbalance(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res.mean_magnitude.value, 0.0, places=6)
        self.assertIsNone(res.max_deviation_percent)
        issue_codes = [i.code for i in issues]
        self.assertIn(WARN_ZERO_MEAN_MAGNITUDE, issue_codes)

    def test_missing_phase_rejected_without_zero_fabrication(self) -> None:
        """Missing Phase C measurement must return None and emit ERR_INCOMPLETE_THREE_PHASE_TELEMETRY."""
        meas_c = Measurement.create_missing("V", self.ts, reason="Sensor broken")
        tp = ThreePhaseQuantity.from_measurements(
            va=make_meas(230.0, "V", ts=self.ts),
            vb=make_meas(230.0, "V", ts=self.ts),
            vc=meas_c,
            asset_id="TX-01",
            timestamp=self.ts,
        )
        res, issues = calculate_phase_magnitude_imbalance(tp, "VOLTAGE")
        self.assertIsNone(res)
        issue_codes = [i.code for i in issues]
        self.assertIn(ERR_INCOMPLETE_THREE_PHASE_TELEMETRY, issue_codes)

    def test_negative_and_non_finite_magnitudes_rejected(self) -> None:
        """Negative magnitude and NaN/Inf must be rejected."""
        # Negative magnitude
        tp_neg = ThreePhaseQuantity.from_measurements(
            va=make_meas(-10.0, "V", ts=self.ts),
            vb=make_meas(230.0, "V", ts=self.ts),
            vc=make_meas(230.0, "V", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        res, issues = calculate_phase_magnitude_imbalance(tp_neg, "VOLTAGE")
        self.assertIsNone(res)
        self.assertTrue(any(i.code == "ERR_PHYSICAL_BOUNDARY" for i in issues))

        # NaN
        tp_nan = ThreePhaseQuantity.from_measurements(
            va=make_meas(float("nan"), "V", ts=self.ts),
            vb=make_meas(230.0, "V", ts=self.ts),
            vc=make_meas(230.0, "V", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        res_nan, issues_nan = calculate_phase_magnitude_imbalance(tp_nan, "VOLTAGE")
        self.assertIsNone(res_nan)
        self.assertTrue(any(i.code == "ERR_NON_FINITE_INPUT" for i in issues_nan))


class TestGroup2SymmetricalComponents(unittest.TestCase):
    """
    Tests for Category B: Fortescue Symmetrical Components on valid complex phasors.
    Verifies ABC positive, negative, zero sequences, inverse reconstruction, and sequence ratios.
    """

    def setUp(self) -> None:
        self.ts = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    def test_ideal_balanced_abc_positive_sequence(self) -> None:
        """
        Ideal balanced ABC positive sequence:
        Va = 230∠0°, Vb = 230∠-120°, Vc = 230∠+120°
        Expectations:
        V1 = 230∠0°, V0 = 0, V2 = 0, VUF = 0.0%
        """
        tp = ThreePhaseQuantity.from_phasors(
            mag_a=make_meas(230.0, "V", ts=self.ts),
            ang_a=make_meas(0.0, "degrees", ts=self.ts),
            mag_b=make_meas(230.0, "V", ts=self.ts),
            ang_b=make_meas(-120.0, "degrees", ts=self.ts),
            mag_c=make_meas(230.0, "V", ts=self.ts),
            ang_c=make_meas(120.0, "degrees", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
            phase_sequence=PhaseSequence.ABC,
        )
        res, issues = calculate_symmetrical_components(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        self.assertEqual(len(issues), 0)

        # Sequence components
        self.assertAlmostEqual(res.positive_sequence_magnitude.value, 230.0, places=4)
        self.assertAlmostEqual(res.zero_sequence_magnitude.value, 0.0, places=4)
        self.assertAlmostEqual(res.negative_sequence_magnitude.value, 0.0, places=4)

        # Angles
        self.assertAlmostEqual(res.positive_sequence.angle_deg, 0.0, places=4)

        # Ratios
        self.assertIsNotNone(res.negative_sequence_ratio_percent)
        self.assertAlmostEqual(res.negative_sequence_ratio_percent.value, 0.0, places=4)
        self.assertAlmostEqual(res.zero_sequence_ratio_percent.value, 0.0, places=4)

        # Reconstruction error must be negligible
        self.assertLess(res.reconstruction_max_error, 1e-9)

    def test_ideal_balanced_negative_sequence(self) -> None:
        """
        Ideal balanced negative sequence:
        Va = 230∠0°, Vb = 230∠+120°, Vc = 230∠-120° (phase order reversed)
        Expectations:
        V2 = 230∠0°, V1 = 0, V0 = 0
        Since V1 = 0, VUF denominator is degenerate -> emits ERR_DEGENERATE_POSITIVE_SEQUENCE and VUF is None.
        """
        tp = ThreePhaseQuantity.from_phasors(
            mag_a=make_meas(230.0, "V", ts=self.ts),
            ang_a=make_meas(0.0, "degrees", ts=self.ts),
            mag_b=make_meas(230.0, "V", ts=self.ts),
            ang_b=make_meas(120.0, "degrees", ts=self.ts),
            mag_c=make_meas(230.0, "V", ts=self.ts),
            ang_c=make_meas(-120.0, "degrees", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
            phase_sequence=PhaseSequence.ABC,
        )
        res, issues = calculate_symmetrical_components(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res.negative_sequence_magnitude.value, 230.0, places=4)
        self.assertAlmostEqual(res.positive_sequence_magnitude.value, 0.0, places=4)
        self.assertAlmostEqual(res.zero_sequence_magnitude.value, 0.0, places=4)

        # Degenerate denominator safety
        self.assertIsNone(res.negative_sequence_ratio_percent)
        self.assertTrue(any(i.code == ERR_DEGENERATE_POSITIVE_SEQUENCE for i in issues))
        self.assertLess(res.reconstruction_max_error, 1e-9)

    def test_pure_zero_sequence(self) -> None:
        """
        Pure zero sequence:
        Va = 100∠0°, Vb = 100∠0°, Vc = 100∠0°
        Expectations:
        V0 = 100∠0°, V1 = 0, V2 = 0
        """
        tp = ThreePhaseQuantity.from_phasors(
            mag_a=make_meas(100.0, "V", ts=self.ts),
            ang_a=make_meas(0.0, "degrees", ts=self.ts),
            mag_b=make_meas(100.0, "V", ts=self.ts),
            ang_b=make_meas(0.0, "degrees", ts=self.ts),
            mag_c=make_meas(100.0, "V", ts=self.ts),
            ang_c=make_meas(0.0, "degrees", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
            phase_sequence=PhaseSequence.ABC,
        )
        res, issues = calculate_symmetrical_components(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res.zero_sequence_magnitude.value, 100.0, places=4)
        self.assertAlmostEqual(res.positive_sequence_magnitude.value, 0.0, places=4)
        self.assertAlmostEqual(res.negative_sequence_magnitude.value, 0.0, places=4)
        self.assertLess(res.reconstruction_max_error, 1e-9)

    def test_known_mixed_sequence_components_and_reconstruction(self) -> None:
        """
        Construct known sequence components:
        V0 = 10∠0°, V1 = 200∠0°, V2 = 20∠30°
        Synthesize phase phasors, run transformation, verify exact recovery of V0, V1, V2.
        """
        v0 = complex(10.0, 0.0)
        v1 = complex(200.0, 0.0)
        v2 = 20.0 * cmath.exp(1j * math.radians(30.0))

        # Phase synthesis
        op_a = cmath.exp(1j * 2.0 * math.pi / 3.0)
        op_a2 = op_a * op_a

        va = v0 + v1 + v2
        vb = v0 + op_a2 * v1 + op_a * v2
        vc = v0 + op_a * v1 + op_a2 * v2

        tp = ThreePhaseQuantity.from_phasors(
            mag_a=make_meas(abs(va), "V", ts=self.ts),
            ang_a=make_meas(math.degrees(cmath.phase(va)), "degrees", ts=self.ts),
            mag_b=make_meas(abs(vb), "V", ts=self.ts),
            ang_b=make_meas(math.degrees(cmath.phase(vb)), "degrees", ts=self.ts),
            mag_c=make_meas(abs(vc), "V", ts=self.ts),
            ang_c=make_meas(math.degrees(cmath.phase(vc)), "degrees", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
            phase_sequence=PhaseSequence.ABC,
        )

        res, issues = calculate_symmetrical_components(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        self.assertEqual(len(issues), 0)

        self.assertAlmostEqual(res.zero_sequence_magnitude.value, 10.0, places=4)
        self.assertAlmostEqual(res.positive_sequence_magnitude.value, 200.0, places=4)
        self.assertAlmostEqual(res.negative_sequence_magnitude.value, 20.0, places=4)

        # Expected VUF = (20 / 200) * 100 = 10.0%
        self.assertAlmostEqual(res.negative_sequence_ratio_percent.value, 10.0, places=4)
        # Expected V0UF = (10 / 200) * 100 = 5.0%
        self.assertAlmostEqual(res.zero_sequence_ratio_percent.value, 5.0, places=4)

        self.assertLess(res.reconstruction_max_error, 1e-9)

    def test_current_symmetrical_components_calculates_neutral_current(self) -> None:
        """
        For current phasors in 4-wire system, In = -(Ia + Ib + Ic) = -3 * I0.
        Verify In magnitude = 3 * |I0|.
        """
        # Unbalanced currents with zero-sequence component
        tp = ThreePhaseQuantity.from_phasors(
            mag_a=make_meas(100.0, "A", ts=self.ts),
            ang_a=make_meas(0.0, "degrees", ts=self.ts),
            mag_b=make_meas(80.0, "A", ts=self.ts),
            ang_b=make_meas(-120.0, "degrees", ts=self.ts),
            mag_c=make_meas(70.0, "A", ts=self.ts),
            ang_c=make_meas(120.0, "degrees", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
            phase_sequence=PhaseSequence.ABC,
        )
        res, issues = calculate_symmetrical_components(tp, "CURRENT")
        self.assertIsNotNone(res)
        self.assertIsNotNone(res.neutral_current)
        self.assertIsNotNone(res.neutral_current_magnitude)

        expected_in_mag = 3.0 * res.zero_sequence_magnitude.value
        self.assertAlmostEqual(res.neutral_current_magnitude.value, expected_in_mag, places=4)


class TestGroup3AngleAbsenceAndConventions(unittest.TestCase):
    """
    Tests for Category B & C: Angle absence guard, magnitude-only rejection, and sequence conventions.
    """

    def setUp(self) -> None:
        self.ts = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    def test_magnitude_only_input_rejected_for_symmetrical_components(self) -> None:
        """Magnitude-only telemetry must NEVER fabricate angles or symmetrical components."""
        tp = ThreePhaseQuantity.from_measurements(
            va=make_meas(230.0, "V", ts=self.ts),
            vb=make_meas(230.0, "V", ts=self.ts),
            vc=make_meas(230.0, "V", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        self.assertFalse(tp.has_complex_phasors)
        res, issues = calculate_symmetrical_components(tp, "VOLTAGE")
        self.assertIsNone(res)
        issue_codes = [i.code for i in issues]
        self.assertIn(ERR_MISSING_PHASOR_ANGLES, issue_codes)

    def test_acb_reverse_phase_sequence_convention(self) -> None:
        """
        Under configured ACB sequence rotation, a physical sequence of A -> C -> B
        is the positive-sequence component.
        """
        # Va=230∠0°, Vb=230∠+120°, Vc=230∠-120°
        tp = ThreePhaseQuantity.from_phasors(
            mag_a=make_meas(230.0, "V", ts=self.ts),
            ang_a=make_meas(0.0, "degrees", ts=self.ts),
            mag_b=make_meas(230.0, "V", ts=self.ts),
            ang_b=make_meas(120.0, "degrees", ts=self.ts),
            mag_c=make_meas(230.0, "V", ts=self.ts),
            ang_c=make_meas(-120.0, "degrees", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
            phase_sequence=PhaseSequence.ACB,
        )
        res, issues = calculate_symmetrical_components(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        # In ACB, A->B(+120)->C(-120) corresponds to positive sequence!
        self.assertAlmostEqual(res.positive_sequence_magnitude.value, 230.0, places=4)
        self.assertAlmostEqual(res.negative_sequence_magnitude.value, 0.0, places=4)
        self.assertLess(res.reconstruction_max_error, 1e-9)


class TestGroup4NumericalSafetyAndChronology(unittest.TestCase):
    """
    Tests for Category B & C: Numerical safety, near-zero denominators, and timestamp integrity.
    """

    def setUp(self) -> None:
        self.ts = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    def test_mismatched_timestamps_across_phases_rejected(self) -> None:
        """Measurements with timestamps diverging by > 1.0 s cannot be combined."""
        ts_a = self.ts
        ts_b = self.ts + timedelta(seconds=5.0)  # Diverges by 5s
        ts_c = self.ts

        tp = ThreePhaseQuantity.from_measurements(
            va=make_meas(230.0, "V", ts=ts_a),
            vb=make_meas(230.0, "V", ts=ts_b),
            vc=make_meas(230.0, "V", ts=ts_c),
            asset_id="TX-01",
            timestamp=ts_a,
        )
        res, issues = calculate_phase_magnitude_imbalance(tp, "VOLTAGE")
        self.assertIsNone(res)
        issue_codes = [i.code for i in issues]
        self.assertIn(ERR_MISMATCHED_PHASE_TIMESTAMPS, issue_codes)

    def test_positive_sequence_near_zero_avoids_division_by_zero(self) -> None:
        """When positive sequence magnitude is 1e-8 V (<= 1e-6 V), ratio returns None and emits diagnostic."""
        tp = ThreePhaseQuantity.from_phasors(
            mag_a=make_meas(1e-8, "V", ts=self.ts),
            ang_a=make_meas(0.0, "degrees", ts=self.ts),
            mag_b=make_meas(1e-8, "V", ts=self.ts),
            ang_b=make_meas(-120.0, "degrees", ts=self.ts),
            mag_c=make_meas(1e-8, "V", ts=self.ts),
            ang_c=make_meas(120.0, "degrees", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
            phase_sequence=PhaseSequence.ABC,
        )
        res, issues = calculate_symmetrical_components(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        self.assertIsNone(res.negative_sequence_ratio_percent)
        issue_codes = [i.code for i in issues]
        self.assertIn(ERR_DEGENERATE_POSITIVE_SEQUENCE, issue_codes)


class TestGroup5EvidenceClassificationAndPropagation(unittest.TestCase):
    """
    Tests for Category C: Evidence classification propagation.
    MEASURED -> CALCULATED. MODELED -> MODELED. SUSPECT quality propagation.
    """

    def setUp(self) -> None:
        self.ts = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    def test_measured_inputs_produce_calculated_outputs(self) -> None:
        """Valid measured inputs produce CALCULATED outputs, never MEASURED."""
        tp = ThreePhaseQuantity.from_measurements(
            va=make_meas(230.0, "V", evidence=EvidenceClassification.MEASURED, ts=self.ts),
            vb=make_meas(230.0, "V", evidence=EvidenceClassification.MEASURED, ts=self.ts),
            vc=make_meas(230.0, "V", evidence=EvidenceClassification.MEASURED, ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        res, _ = calculate_phase_magnitude_imbalance(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        self.assertEqual(res.mean_magnitude.evidence, EvidenceClassification.CALCULATED)
        self.assertEqual(res.max_absolute_deviation.evidence, EvidenceClassification.CALCULATED)
        self.assertEqual(res.max_deviation_percent.evidence, EvidenceClassification.CALCULATED)

    def test_modeled_input_retains_modeled_evidence(self) -> None:
        """If any input was MODELED, derived metrics must retain MODELED classification."""
        tp = ThreePhaseQuantity.from_measurements(
            va=make_meas(230.0, "V", evidence=EvidenceClassification.MEASURED, ts=self.ts),
            vb=make_meas(230.0, "V", evidence=EvidenceClassification.MODELED, ts=self.ts),
            vc=make_meas(230.0, "V", evidence=EvidenceClassification.MEASURED, ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        res, _ = calculate_phase_magnitude_imbalance(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        self.assertEqual(res.mean_magnitude.evidence, EvidenceClassification.MODELED)

    def test_suspect_quality_propagates_to_results(self) -> None:
        """If any phase has SUSPECT quality, outputs must be tagged SUSPECT."""
        tp = ThreePhaseQuantity.from_measurements(
            va=make_meas(230.0, "V", quality=MeasurementQuality.GOOD, ts=self.ts),
            vb=make_meas(230.0, "V", quality=MeasurementQuality.SUSPECT, ts=self.ts),
            vc=make_meas(230.0, "V", quality=MeasurementQuality.GOOD, ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        res, _ = calculate_phase_magnitude_imbalance(tp, "VOLTAGE")
        self.assertIsNotNone(res)
        self.assertEqual(res.mean_magnitude.quality, MeasurementQuality.SUSPECT)


class TestGroup6EvidenceGroundedDerating(unittest.TestCase):
    """
    Tests for Category D: Evidence-grounded derating analytics.
    Verifies conductor capacity derating, unverified parameters handling, and limits.
    """

    def setUp(self) -> None:
        self.ts = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
        self.spec = make_spec("TX-01")

    def test_max_phase_current_capacity_derating(self) -> None:
        """
        When phase currents are unbalanced: Ia=120A, Ib=90A, Ic=90A -> Mean=100A, Max=120A.
        Derating factor = 100 / 120 = 0.833 pu.
        Ensures transformer total loading is limited so Phase A does not exceed rated current.
        """
        tp_i = ThreePhaseQuantity.from_measurements(
            va=make_meas(120.0, "A", ts=self.ts),
            vb=make_meas(90.0, "A", ts=self.ts),
            vc=make_meas(90.0, "A", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        i_imb, _ = calculate_phase_magnitude_imbalance(tp_i, "CURRENT")

        config = DeratingConfiguration(method=DeratingMethod.MAX_PHASE_CURRENT_CAPACITY)
        res, issues = calculate_transformer_derating(
            current_imbalance=i_imb,
            current_symmetrical=None,
            voltage_imbalance=None,
            voltage_symmetrical=None,
            asset_spec=self.spec,
            derating_config=config,
            timestamp=self.ts,
        )
        self.assertIsNotNone(res)
        self.assertEqual(res.status, "CALCULATED")
        self.assertTrue(res.is_derated)
        self.assertIsNotNone(res.derating_factor_pu)
        self.assertAlmostEqual(res.derating_factor_pu.value, 100.0 / 120.0, places=4)
        self.assertEqual(res.derating_factor_pu.unit, "pu")

    def test_balanced_current_requires_no_derating(self) -> None:
        """Balanced currents (Ia=Ib=Ic=100A) -> derating factor = 1.0 pu, is_derated = False."""
        tp_i = ThreePhaseQuantity.from_measurements(
            va=make_meas(100.0, "A", ts=self.ts),
            vb=make_meas(100.0, "A", ts=self.ts),
            vc=make_meas(100.0, "A", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        i_imb, _ = calculate_phase_magnitude_imbalance(tp_i, "CURRENT")

        res, _ = calculate_transformer_derating(
            current_imbalance=i_imb,
            current_symmetrical=None,
            voltage_imbalance=None,
            voltage_symmetrical=None,
            asset_spec=self.spec,
            timestamp=self.ts,
        )
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res.derating_factor_pu.value, 1.0, places=4)
        self.assertFalse(res.is_derated)

    def test_loss_based_derating_without_verified_parameters_returns_unknown(self) -> None:
        """
        Requesting loss-based negative-sequence derating without verified loss ratio (R)
        and eddy loss factor (PEC) must return UNKNOWN and emit WARN_UNVERIFIED_DERATING_PARAMETERS.
        """
        config = DeratingConfiguration(
            method=DeratingMethod.LOSS_BASED_NEGATIVE_SEQUENCE,
            loss_ratio_r=None,  # Missing!
            eddy_loss_factor_pec=None,  # Missing!
        )
        res, issues = calculate_transformer_derating(
            current_imbalance=None,
            current_symmetrical=None,
            voltage_imbalance=None,
            voltage_symmetrical=None,
            asset_spec=self.spec,
            derating_config=config,
            timestamp=self.ts,
        )
        self.assertIsNotNone(res)
        self.assertEqual(res.status, "UNVERIFIED")
        self.assertIsNone(res.derating_factor_pu)
        issue_codes = [i.code for i in issues]
        self.assertIn(WARN_UNVERIFIED_DERATING_PARAMETERS, issue_codes)

    def test_operational_limits_exceedance_emits_warnings(self) -> None:
        """Exceeding max_voltage_unbalance_percent or max_current_unbalance_percent emits warnings."""
        # Voltage unbalance > 2.0%
        tp_v = ThreePhaseQuantity.from_measurements(
            va=make_meas(250.0, "V", ts=self.ts),
            vb=make_meas(220.0, "V", ts=self.ts),
            vc=make_meas(220.0, "V", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        v_imb, _ = calculate_phase_magnitude_imbalance(tp_v, "VOLTAGE")

        # Current unbalance > 10.0%
        tp_i = ThreePhaseQuantity.from_measurements(
            va=make_meas(150.0, "A", ts=self.ts),
            vb=make_meas(90.0, "A", ts=self.ts),
            vc=make_meas(90.0, "A", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        i_imb, _ = calculate_phase_magnitude_imbalance(tp_i, "CURRENT")

        res, issues = calculate_transformer_derating(
            current_imbalance=i_imb,
            current_symmetrical=None,
            voltage_imbalance=v_imb,
            voltage_symmetrical=None,
            asset_spec=self.spec,
            timestamp=self.ts,
        )
        issue_codes = [i.code for i in issues]
        self.assertIn(WARN_VOLTAGE_UNBALANCE_EXCEEDS_LIMIT, issue_codes)
        self.assertIn(WARN_CURRENT_UNBALANCE_EXCEEDS_LIMIT, issue_codes)


class TestGroup7EnginePipelineIntegration(unittest.TestCase):
    """
    Tests for PhaseImbalanceEngine end-to-end execution.
    Verifies synthesis of ElectricalFeaturesResult, TransformerLoadingResult,
    ThreePhaseQuantity inputs, and PhaseImbalanceResult contract packaging.
    """

    def setUp(self) -> None:
        self.ts = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
        self.spec = make_spec("TX-01")
        self.engine = PhaseImbalanceEngine(asset_spec=self.spec)

    def test_engine_compute_from_features_magnitude_only(self) -> None:
        """Engine automatically extracts magnitude-only three-phase quantities from ElectricalFeaturesResult."""
        features = ElectricalFeaturesResult(
            is_computed=True,
            v_a_rms=make_meas(240.0, "V", ts=self.ts),
            v_b_rms=make_meas(220.0, "V", ts=self.ts),
            v_c_rms=make_meas(220.0, "V", ts=self.ts),
            i_a_rms=make_meas(110.0, "A", ts=self.ts),
            i_b_rms=make_meas(100.0, "A", ts=self.ts),
            i_c_rms=make_meas(90.0, "A", ts=self.ts),
        )
        loading = TransformerLoadingResult(
            is_computed=True,
            loading_ratio_pu=make_meas(0.75, "pu", ts=self.ts),
        )
        inp = PhaseImbalanceInput(
            features=features,
            loading=loading,
            asset_spec=self.spec,
        )

        res, issues = self.engine.compute_imbalance(inp)
        self.assertTrue(res.is_computed)
        self.assertIsNotNone(res.phase_voltage_unbalance_rate_pvur)
        self.assertAlmostEqual(res.phase_voltage_unbalance_rate_pvur.value, (13.333333 / 226.666667) * 100.0, places=3)
        # Symmetrical components are None because no angles were provided
        self.assertIsNone(res.voltage_unbalance_factor_vuf)
        self.assertIsNone(res.current_unbalance_factor_cuf)
        self.assertIsNone(res.neutral_current_a)

        # Derating factor is calculated from current magnitude imbalance
        self.assertIsNotNone(res.derating_factor_pu)
        self.assertAlmostEqual(res.derating_factor_pu.value, 100.0 / 110.0, places=4)

    def test_engine_compute_from_explicit_synchrophasors(self) -> None:
        """When explicit ThreePhaseQuantity with phasors is provided, all sequence metrics and ratios populate."""
        tp_v = ThreePhaseQuantity.from_phasors(
            mag_a=make_meas(230.0, "V", ts=self.ts),
            ang_a=make_meas(0.0, "degrees", ts=self.ts),
            mag_b=make_meas(225.0, "V", ts=self.ts),
            ang_b=make_meas(-122.0, "degrees", ts=self.ts),
            mag_c=make_meas(232.0, "V", ts=self.ts),
            ang_c=make_meas(119.0, "degrees", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )
        tp_i = ThreePhaseQuantity.from_phasors(
            mag_a=make_meas(105.0, "A", ts=self.ts),
            ang_a=make_meas(-10.0, "degrees", ts=self.ts),
            mag_b=make_meas(98.0, "A", ts=self.ts),
            ang_b=make_meas(-135.0, "degrees", ts=self.ts),
            mag_c=make_meas(95.0, "A", ts=self.ts),
            ang_c=make_meas(105.0, "degrees", ts=self.ts),
            asset_id="TX-01",
            timestamp=self.ts,
        )

        inp = PhaseImbalanceInput(
            features=ElectricalFeaturesResult(),
            loading=TransformerLoadingResult(),
            asset_spec=self.spec,
            voltage_three_phase=tp_v,
            current_three_phase=tp_i,
        )

        res, issues = self.engine.compute_imbalance(inp)
        self.assertTrue(res.is_computed)
        self.assertIsNotNone(res.voltage_unbalance_factor_vuf)
        self.assertIsNotNone(res.current_unbalance_factor_cuf)
        self.assertIsNotNone(res.neutral_current_a)
        self.assertIsNotNone(res.derating_factor_pu)
        self.assertEqual(res.voltage_unbalance_factor_vuf.unit, "percent")
        self.assertEqual(res.current_unbalance_factor_cuf.unit, "percent")
        self.assertEqual(res.neutral_current_a.unit, "A")
        self.assertEqual(res.derating_factor_pu.unit, "pu")


if __name__ == "__main__":
    unittest.main()
