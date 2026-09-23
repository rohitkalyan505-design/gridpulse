"""
GridPulse — Phase 2 Step 1 Scientific Architecture Contract Tests
Validates the structural integrity, invariants, and boundary conditions of
shared scientific contracts.
"""

from datetime import datetime, timezone
import hashlib
import unittest

from scientific.contracts.enums import (
    CoolingType,
    EvidenceClassification,
    InsulationClass,
    IssueSeverity,
    MeasurementQuality,
    WindingMaterial,
)
from scientific.contracts.standards import StandardReference
from scientific.contracts.measurement import (
    CANONICAL_UNITS,
    Measurement,
    UnitMetadata,
)
from scientific.contracts.asset import (
    OperationalLimits,
    TransformerAssetSpec,
)
from scientific.contracts.provenance import (
    EngineeringAssumption,
    ProvenanceMetadata,
    compute_telemetry_digest,
)
from scientific.contracts.issues import (
    AssetSpecError,
    ContractViolationError,
    InsufficientTelemetryError,
    PhysicalBoundaryError,
    ProcessingIssue,
    ScientificEngineError,
    TelemetryValidationError,
)
from scientific.contracts.results import (
    AnomalyAssessmentResult,
    AssetDecisionResult,
    ElectricalFeaturesResult,
    PhaseImbalanceResult,
    ScientificRunResult,
    ThermalStateResult,
    TransformerLoadingResult,
    ValidationSummary,
)

# Test importability of module-specific contracts
from scientific.ingestion.contracts import RawTelemetryBatch, RawTelemetryReading, RawTelemetryRecord
from scientific.validation.contracts import PhysicalBoundaryRule, ValidatedTelemetryBatch, ValidatedTelemetryRecord
from scientific.features.contracts import ElectricalCalculationInput, TransformerLoadingInput
from scientific.thermal.contracts import ThermalAnalysisInput, ThermalModelParameters
from scientific.imbalance.contracts import PhaseImbalanceInput
from scientific.anomaly.contracts import AnomalyBaselineSpec, AnomalyDetectionInput
from scientific.decisions.contracts import DecisionIntelligenceInput, DecisionRuleCriteria


class TestEvidenceClassification(unittest.TestCase):
    """Validates the locked 5-level scientific evidence classification."""

    def test_locked_evidence_values(self):
        expected = {"MEASURED", "CALCULATED", "MODELED", "INFERRED", "UNKNOWN"}
        actual = {e.value for e in EvidenceClassification}
        self.assertEqual(expected, actual)

    def test_evidence_is_str_subclass(self):
        self.assertEqual(EvidenceClassification.MEASURED, "MEASURED")
        self.assertEqual(EvidenceClassification.CALCULATED, "CALCULATED")
        self.assertEqual(EvidenceClassification.MODELED, "MODELED")
        self.assertEqual(EvidenceClassification.INFERRED, "INFERRED")
        self.assertEqual(EvidenceClassification.UNKNOWN, "UNKNOWN")


class TestMeasurementQuality(unittest.TestCase):
    """Validates standardized telemetry data quality states."""

    def test_quality_values(self):
        expected = {"GOOD", "SUSPECT", "BAD", "MISSING", "OUT_OF_RANGE", "CALIBRATION_EXPIRED"}
        actual = {q.value for q in MeasurementQuality}
        self.assertEqual(expected, actual)


class TestMeasurementRepresentation(unittest.TestCase):
    """Validates Measurement[T] contracts and invariants."""

    def test_valid_measurement_creation(self):
        now_utc = datetime.now(timezone.utc)
        m = Measurement(
            value=230.5,
            unit="V",
            evidence=EvidenceClassification.MEASURED,
            quality=MeasurementQuality.GOOD,
            timestamp=now_utc,
            sensor_id="PT-A01",
        )
        self.assertEqual(m.value, 230.5)
        self.assertEqual(m.unit, "V")
        self.assertEqual(m.evidence, EvidenceClassification.MEASURED)
        self.assertEqual(m.quality, MeasurementQuality.GOOD)
        self.assertEqual(m.sensor_id, "PT-A01")

    def test_timezone_naive_rejected(self):
        naive_dt = datetime(2026, 9, 23, 12, 0, 0)  # No tzinfo
        with self.assertRaises(ValueError) as ctx:
            Measurement(
                value=230.5,
                unit="V",
                evidence=EvidenceClassification.MEASURED,
                quality=MeasurementQuality.GOOD,
                timestamp=naive_dt,
            )
        self.assertIn("timezone-aware", str(ctx.exception))

    def test_missing_data_invariant_enforced(self):
        """Missing telemetry must be explicitly None value with UNKNOWN evidence."""
        now_utc = datetime.now(timezone.utc)

        # Illegal: Missing quality with non-None value
        with self.assertRaises(ValueError) as ctx:
            Measurement(
                value=100.0,
                unit="A",
                evidence=EvidenceClassification.UNKNOWN,
                quality=MeasurementQuality.MISSING,
                timestamp=now_utc,
            )
        self.assertIn("value=None", str(ctx.exception))

        # Illegal: Missing quality with non-UNKNOWN evidence
        with self.assertRaises(ValueError) as ctx:
            Measurement(
                value=None,
                unit="A",
                evidence=EvidenceClassification.CALCULATED,
                quality=MeasurementQuality.MISSING,
                timestamp=now_utc,
            )
        self.assertIn("must carry evidence=UNKNOWN", str(ctx.exception))

        # Illegal: None value with GOOD quality
        with self.assertRaises(ValueError) as ctx:
            Measurement(
                value=None,
                unit="A",
                evidence=EvidenceClassification.UNKNOWN,
                quality=MeasurementQuality.GOOD,
                timestamp=now_utc,
            )
        self.assertIn("quality MISSING or BAD", str(ctx.exception))

    def test_create_missing_factory(self):
        now_utc = datetime.now(timezone.utc)
        m = Measurement.create_missing("degC", now_utc, sensor_id="TEMP-01", reason="Sensor offline")
        self.assertIsNone(m.value)
        self.assertEqual(m.quality, MeasurementQuality.MISSING)
        self.assertEqual(m.evidence, EvidenceClassification.UNKNOWN)
        self.assertEqual(m.unit, "degC")
        self.assertEqual(m.metadata.get("missing_reason"), "Sensor offline")


class TestUnitMetadata(unittest.TestCase):
    """Validates basic unit metadata catalog."""

    def test_canonical_units_catalog(self):
        self.assertIn("V", CANONICAL_UNITS)
        self.assertIn("A", CANONICAL_UNITS)
        self.assertIn("kW", CANONICAL_UNITS)
        self.assertIn("kVA", CANONICAL_UNITS)
        self.assertIn("degC", CANONICAL_UNITS)
        self.assertIn("Hz", CANONICAL_UNITS)

        v_unit = CANONICAL_UNITS["V"]
        self.assertEqual(v_unit.dimension, "voltage")
        self.assertEqual(v_unit.canonical_unit, "V")


class TestTransformerAssetSpec(unittest.TestCase):
    """Validates transformer asset specifications and boundary rules."""

    def setUp(self):
        self.valid_spec = TransformerAssetSpec(
            asset_id="TX-SUB01-DT04",
            rated_power_kva=500.0,
            primary_voltage_v=11000.0,
            secondary_voltage_v=433.0,
            rated_frequency_hz=50.0,
            phases=3,
            cooling_type=CoolingType.ONAN,
            winding_material=WindingMaterial.COPPER,
            insulation_class=InsulationClass.CLASS_A_105,
            vector_group="Dyn11",
            impedance_percent=4.5,
        )

    def test_valid_spec_creation(self):
        self.assertEqual(self.valid_spec.asset_id, "TX-SUB01-DT04")
        self.assertEqual(self.valid_spec.rated_power_kva, 500.0)
        self.assertEqual(self.valid_spec.phases, 3)

    def test_spec_invalid_rated_power(self):
        with self.assertRaises(ValueError):
            TransformerAssetSpec(
                asset_id="TX-INVALID",
                rated_power_kva=-10.0,  # Negative
                primary_voltage_v=11000.0,
                secondary_voltage_v=433.0,
                rated_frequency_hz=50.0,
                phases=3,
                cooling_type=CoolingType.ONAN,
                winding_material=WindingMaterial.COPPER,
                insulation_class=InsulationClass.CLASS_A_105,
            )

    def test_spec_invalid_frequency(self):
        with self.assertRaises(ValueError):
            TransformerAssetSpec(
                asset_id="TX-INVALID",
                rated_power_kva=500.0,
                primary_voltage_v=11000.0,
                secondary_voltage_v=433.0,
                rated_frequency_hz=45.0,  # Non-standard
                phases=3,
                cooling_type=CoolingType.ONAN,
                winding_material=WindingMaterial.COPPER,
                insulation_class=InsulationClass.CLASS_A_105,
            )


class TestStandardReferenceAndAssumptions(unittest.TestCase):
    """Validates standards reference representation and explicit assumptions."""

    def test_standard_reference_structure(self):
        std = StandardReference(
            standard_id="IEEE C57.91",
            edition_year="2011",
            purpose_context="Guide for Loading Mineral-Oil-Immersed Transformers",
            associated_target="Thermal state model differential equations",
        )
        self.assertEqual(std.standard_id, "IEEE C57.91")
        self.assertEqual(std.edition_year, "2011")
        self.assertIsNotNone(std.purpose_context)

    def test_engineering_assumption_structure(self):
        std = StandardReference(
            standard_id="IEC 60076-7",
            edition_year="2018",
            purpose_context="Loading guide for mineral-oil-immersed power transformers",
        )
        assumption = EngineeringAssumption(
            parameter_name="ambient_temperature_c",
            assumed_value=30.0,
            unit="degC",
            rationale="Local ambient sensor unmetered; applied IEC standard yearly average",
            standard_reference=std,
            sensitivity_impact="HIGH",
        )
        self.assertEqual(assumption.parameter_name, "ambient_temperature_c")
        self.assertEqual(assumption.assumed_value, 30.0)
        self.assertEqual(assumption.sensitivity_impact, "HIGH")

    def test_provenance_digest_computation(self):
        raw_payload = b'{"asset_id": "TX-01", "timestamp": "2026-09-23T12:00:00Z", "va": 230.1}'
        digest = compute_telemetry_digest(raw_payload)
        expected = hashlib.sha256(raw_payload).hexdigest()
        self.assertEqual(digest, expected)
        self.assertEqual(len(digest), 64)

        now_utc = datetime.now(timezone.utc)
        prov = ProvenanceMetadata(
            pipeline_version="0.2.0-step1",
            execution_timestamp=now_utc,
            telemetry_digest=digest,
            asset_id="TX-01",
        )
        self.assertEqual(prov.telemetry_digest, digest)


class TestScientificRunResultStructure(unittest.TestCase):
    """Validates top-level ScientificRunResult container and serialization."""

    def test_result_structure_and_serialization(self):
        now_utc = datetime.now(timezone.utc)
        raw_bytes = b"telemetry_stream_data_test"
        digest = compute_telemetry_digest(raw_bytes)

        provenance = ProvenanceMetadata(
            pipeline_version="0.2.0-step1",
            execution_timestamp=now_utc,
            telemetry_digest=digest,
            asset_id="TX-SUB02-DT007",
            evidence_tally={"MEASURED": 6, "CALCULATED": 0, "MODELED": 0, "INFERRED": 0, "UNKNOWN": 1},
        )
        summary = ValidationSummary(
            total_records=100,
            valid_records=98,
            suspect_records=1,
            bad_records=1,
            missing_records=0,
            dropped_records=0,
        )

        run_result = ScientificRunResult(
            run_id="test-run-uuid-001",
            asset_id="TX-SUB02-DT007",
            time_window_start=now_utc,
            time_window_end=now_utc,
            pipeline_version="0.2.0-step1",
            provenance=provenance,
            validation_summary=summary,
            electrical_features=ElectricalFeaturesResult(is_computed=False),
            transformer_loading=TransformerLoadingResult(is_computed=False),
            thermal_state=ThermalStateResult(is_computed=False),
            phase_imbalance=PhaseImbalanceResult(is_computed=False),
            anomaly_assessment=AnomalyAssessmentResult(is_computed=False),
            decision_intelligence=AssetDecisionResult(is_computed=False),
        )

        d = run_result.to_dict()
        self.assertEqual(d["run_id"], "test-run-uuid-001")
        self.assertEqual(d["asset_id"], "TX-SUB02-DT007")
        self.assertEqual(d["validation_summary"]["valid_records"], 98)
        self.assertFalse(d["electrical_features"]["is_computed"])
        self.assertFalse(d["thermal_state"]["is_computed"])
        self.assertFalse(d["decision_intelligence"]["is_computed"])


class TestNoAlgorithmsInStep1(unittest.TestCase):
    """
    Verifies that Step 1 result contracts do not execute algorithms,
    formulas, or model calculations.
    """

    def test_results_remain_uncomputed(self):
        ef = ElectricalFeaturesResult()
        self.assertFalse(ef.is_computed)
        self.assertIsNone(ef.active_power_kw)

        tl = TransformerLoadingResult()
        self.assertFalse(tl.is_computed)
        self.assertIsNone(tl.loading_ratio_pu)

        ts = ThermalStateResult()
        self.assertFalse(ts.is_computed)
        self.assertIsNone(ts.hot_spot_temp_c)

        pi = PhaseImbalanceResult()
        self.assertFalse(pi.is_computed)
        self.assertIsNone(pi.voltage_unbalance_factor_vuf)

        aa = AnomalyAssessmentResult()
        self.assertFalse(aa.is_computed)
        self.assertIsNone(aa.anomaly_score)

        di = AssetDecisionResult()
        self.assertFalse(di.is_computed)
        self.assertIsNone(di.health_index)


class TestModuleContractImports(unittest.TestCase):
    """Verifies that all scientific subdirectories have cohesive, importable contracts."""

    def test_imports(self):
        self.assertTrue(issubclass(ScientificEngineError, Exception))
        self.assertTrue(issubclass(TelemetryValidationError, ScientificEngineError))
        self.assertTrue(issubclass(PhysicalBoundaryError, ScientificEngineError))
        self.assertTrue(issubclass(InsufficientTelemetryError, ScientificEngineError))
        self.assertTrue(issubclass(ContractViolationError, ScientificEngineError))
        self.assertTrue(issubclass(AssetSpecError, ScientificEngineError))


if __name__ == "__main__":
    unittest.main()
