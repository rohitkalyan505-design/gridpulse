"""
GridPulse — Scientific Result Structures
Part of scientific.contracts (Source of Truth)

Defines future result contracts for the locked GridPulse scientific pipeline:
Electrical Data
→ Data Validation
→ Electrical Calculations
→ Transformer Loading
→ Thermal Analysis
→ Phase Imbalance
→ Anomaly Detection
→ Decision Intelligence
→ Structured Scientific Results

IMPORTANT ARCHITECTURAL RULE:
Step 1 defines purely the typed result structures and data schemas.
It does NOT execute electrical engineering formulas, thermal models,
loss of life calculations, unbalance factors, anomaly algorithms, ML models,
or decision heuristics.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from scientific.contracts.issues import ProcessingIssue
from scientific.contracts.measurement import Measurement
from scientific.contracts.provenance import ProvenanceMetadata


@dataclass(frozen=True)
class ValidationSummary:
    """Summary of data validation stage telemetry checks."""
    total_records: int
    valid_records: int
    suspect_records: int
    bad_records: int
    missing_records: int
    dropped_records: int

    def __post_init__(self) -> None:
        if self.total_records < 0 or self.valid_records < 0:
            raise ValueError("Record counts cannot be negative.")


@dataclass(frozen=True)
class ElectricalFeaturesResult:
    """
    Contract defining deterministic electrical calculation results.
    Preserves both directly measured and closed-form calculated metrics.
    """
    is_computed: bool = False
    v_a_rms: Optional[Measurement[float]] = None
    v_b_rms: Optional[Measurement[float]] = None
    v_c_rms: Optional[Measurement[float]] = None
    v_avg_rms: Optional[Measurement[float]] = None
    i_a_rms: Optional[Measurement[float]] = None
    i_b_rms: Optional[Measurement[float]] = None
    i_c_rms: Optional[Measurement[float]] = None
    i_avg_rms: Optional[Measurement[float]] = None
    active_power_kw: Optional[Measurement[float]] = None
    reactive_power_kvar: Optional[Measurement[float]] = None
    apparent_power_kva: Optional[Measurement[float]] = None
    power_factor: Optional[Measurement[float]] = None
    frequency_hz: Optional[Measurement[float]] = None
    # Explicit coexistence of measured vs calculated quantities
    apparent_power_measured_kva: Optional[Measurement[float]] = None
    apparent_power_calculated_kva: Optional[Measurement[float]] = None
    power_factor_measured: Optional[Measurement[float]] = None
    power_factor_calculated: Optional[Measurement[float]] = None
    calculation_provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransformerLoadingResult:
    """
    Contract defining future transformer loading results.
    Loading algorithms and capacity calculations are deferred to later steps.
    """
    is_computed: bool = False
    loading_ratio_pu: Optional[Measurement[float]] = None
    peak_loading_ratio_pu: Optional[Measurement[float]] = None
    total_apparent_power_kva: Optional[Measurement[float]] = None
    phase_a_loading_pu: Optional[Measurement[float]] = None
    phase_b_loading_pu: Optional[Measurement[float]] = None
    phase_c_loading_pu: Optional[Measurement[float]] = None
    is_overloaded: bool = False


@dataclass(frozen=True)
class ThermalStateResult:
    """
    Contract defining future thermal analysis results.
    Thermal ODE differential equations and loss of life calculations
    are deferred to later steps.
    """
    is_computed: bool = False
    top_oil_temp_c: Optional[Measurement[float]] = None
    hot_spot_temp_c: Optional[Measurement[float]] = None
    ambient_temp_c: Optional[Measurement[float]] = None
    aging_acceleration_factor: Optional[Measurement[float]] = None
    equivalent_loss_of_life_hours: Optional[Measurement[float]] = None
    thermal_model_standard: Optional[str] = None


@dataclass(frozen=True)
class PhaseImbalanceResult:
    """
    Contract defining future phase imbalance results.
    Symmetrical component transformations and unbalance factor formulas
    are deferred to later steps.
    """
    is_computed: bool = False
    voltage_unbalance_factor_vuf: Optional[Measurement[float]] = None
    phase_voltage_unbalance_rate_pvur: Optional[Measurement[float]] = None
    current_unbalance_factor_cuf: Optional[Measurement[float]] = None
    neutral_current_a: Optional[Measurement[float]] = None
    derating_factor_pu: Optional[Measurement[float]] = None


@dataclass(frozen=True)
class AnomalyAssessmentResult:
    """
    Contract defining future anomaly detection results.
    Statistical baseline learning, residual analysis, and ML models
    are deferred to later steps.
    """
    is_computed: bool = False
    anomaly_detected: bool = False
    anomaly_score: Optional[Measurement[float]] = None
    drift_detected: bool = False
    drift_score: Optional[Measurement[float]] = None
    flagged_dimensions: List[str] = field(default_factory=list)
    confidence: Optional[float] = None


@dataclass(frozen=True)
class AssetDecisionResult:
    """
    Contract defining future decision intelligence results.
    Health index weighting, operational risk scoring, and heuristic
    rules are deferred to later steps.
    """
    is_computed: bool = False
    health_index: Optional[Measurement[float]] = None
    risk_category: Optional[str] = None  # e.g., 'LOW', 'MODERATE', 'HIGH', 'CRITICAL'
    action_urgency: Optional[str] = None  # e.g., 'NORMAL', 'MONITOR', 'SCHEDULE_MAINTENANCE', 'IMMEDIATE'
    active_limit_violations: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScientificRunResult:
    """
    Unified immutable container for complete scientific pipeline execution results.
    Guarantees structural consistency, full provenance, and schema stability.
    """
    run_id: str
    asset_id: str
    time_window_start: datetime
    time_window_end: datetime
    pipeline_version: str
    provenance: ProvenanceMetadata
    validation_summary: ValidationSummary
    electrical_features: Optional[ElectricalFeaturesResult] = None
    transformer_loading: Optional[TransformerLoadingResult] = None
    thermal_state: Optional[ThermalStateResult] = None
    phase_imbalance: Optional[PhaseImbalanceResult] = None
    anomaly_assessment: Optional[AnomalyAssessmentResult] = None
    decision_intelligence: Optional[AssetDecisionResult] = None
    issues: List[ProcessingIssue] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.run_id:
            object.__setattr__(self, "run_id", str(uuid.uuid4()))
        if not self.asset_id or not self.asset_id.strip():
            raise ValueError("asset_id must be a non-empty string.")
        if self.time_window_start.tzinfo is None or self.time_window_end.tzinfo is None:
            raise ValueError("time_window timestamps must be timezone-aware (strictly UTC).")
        if self.time_window_end < self.time_window_start:
            raise ValueError("time_window_end cannot precede time_window_start.")

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the result to a clean dictionary representation for export and caching."""
        def serialize_measurement(m: Optional[Measurement[Any]]) -> Optional[Dict[str, Any]]:
            if m is None:
                return None
            return {
                "value": m.value,
                "unit": m.unit,
                "evidence": m.evidence.value,
                "quality": m.quality.value,
                "timestamp": m.timestamp.isoformat(),
                "sensor_id": m.sensor_id,
                "metadata": m.metadata,
            }

        return {
            "run_id": self.run_id,
            "asset_id": self.asset_id,
            "time_window_start": self.time_window_start.isoformat(),
            "time_window_end": self.time_window_end.isoformat(),
            "pipeline_version": self.pipeline_version,
            "provenance": {
                "pipeline_version": self.provenance.pipeline_version,
                "execution_timestamp": self.provenance.execution_timestamp.isoformat(),
                "telemetry_digest": self.provenance.telemetry_digest,
                "asset_id": self.provenance.asset_id,
                "standards_referenced": [
                    {
                        "standard_id": s.standard_id,
                        "edition_year": s.edition_year,
                        "purpose_context": s.purpose_context,
                        "associated_target": s.associated_target,
                    }
                    for s in self.provenance.standards_referenced
                ],
                "assumptions_applied": [
                    {
                        "parameter_name": a.parameter_name,
                        "assumed_value": a.assumed_value,
                        "unit": a.unit,
                        "rationale": a.rationale,
                        "standard_reference": (
                            {
                                "standard_id": a.standard_reference.standard_id,
                                "edition_year": a.standard_reference.edition_year,
                                "purpose_context": a.standard_reference.purpose_context,
                            }
                            if a.standard_reference
                            else None
                        ),
                        "sensitivity_impact": a.sensitivity_impact,
                    }
                    for a in self.provenance.assumptions_applied
                ],
                "evidence_tally": self.provenance.evidence_tally,
            },
            "validation_summary": {
                "total_records": self.validation_summary.total_records,
                "valid_records": self.validation_summary.valid_records,
                "suspect_records": self.validation_summary.suspect_records,
                "bad_records": self.validation_summary.bad_records,
                "missing_records": self.validation_summary.missing_records,
                "dropped_records": self.validation_summary.dropped_records,
            },
            "electrical_features": (
                {
                    "is_computed": self.electrical_features.is_computed,
                    "v_a_rms": serialize_measurement(self.electrical_features.v_a_rms),
                    "v_b_rms": serialize_measurement(self.electrical_features.v_b_rms),
                    "v_c_rms": serialize_measurement(self.electrical_features.v_c_rms),
                    "v_avg_rms": serialize_measurement(self.electrical_features.v_avg_rms),
                    "i_a_rms": serialize_measurement(self.electrical_features.i_a_rms),
                    "i_b_rms": serialize_measurement(self.electrical_features.i_b_rms),
                    "i_c_rms": serialize_measurement(self.electrical_features.i_c_rms),
                    "i_avg_rms": serialize_measurement(self.electrical_features.i_avg_rms),
                    "active_power_kw": serialize_measurement(self.electrical_features.active_power_kw),
                    "reactive_power_kvar": serialize_measurement(self.electrical_features.reactive_power_kvar),
                    "apparent_power_kva": serialize_measurement(self.electrical_features.apparent_power_kva),
                    "power_factor": serialize_measurement(self.electrical_features.power_factor),
                    "frequency_hz": serialize_measurement(self.electrical_features.frequency_hz),
                    "apparent_power_measured_kva": serialize_measurement(self.electrical_features.apparent_power_measured_kva),
                    "apparent_power_calculated_kva": serialize_measurement(self.electrical_features.apparent_power_calculated_kva),
                    "power_factor_measured": serialize_measurement(self.electrical_features.power_factor_measured),
                    "power_factor_calculated": serialize_measurement(self.electrical_features.power_factor_calculated),
                    "calculation_provenance": self.electrical_features.calculation_provenance,
                }
                if self.electrical_features
                else None
            ),
            "transformer_loading": (
                {
                    "is_computed": self.transformer_loading.is_computed,
                    "loading_ratio_pu": serialize_measurement(self.transformer_loading.loading_ratio_pu),
                    "peak_loading_ratio_pu": serialize_measurement(self.transformer_loading.peak_loading_ratio_pu),
                    "total_apparent_power_kva": serialize_measurement(self.transformer_loading.total_apparent_power_kva),
                    "phase_a_loading_pu": serialize_measurement(self.transformer_loading.phase_a_loading_pu),
                    "phase_b_loading_pu": serialize_measurement(self.transformer_loading.phase_b_loading_pu),
                    "phase_c_loading_pu": serialize_measurement(self.transformer_loading.phase_c_loading_pu),
                    "is_overloaded": self.transformer_loading.is_overloaded,
                }
                if self.transformer_loading
                else None
            ),
            "thermal_state": (
                {
                    "is_computed": self.thermal_state.is_computed,
                    "top_oil_temp_c": serialize_measurement(self.thermal_state.top_oil_temp_c),
                    "hot_spot_temp_c": serialize_measurement(self.thermal_state.hot_spot_temp_c),
                    "ambient_temp_c": serialize_measurement(self.thermal_state.ambient_temp_c),
                    "aging_acceleration_factor": serialize_measurement(self.thermal_state.aging_acceleration_factor),
                    "equivalent_loss_of_life_hours": serialize_measurement(self.thermal_state.equivalent_loss_of_life_hours),
                    "thermal_model_standard": self.thermal_state.thermal_model_standard,
                }
                if self.thermal_state
                else None
            ),
            "phase_imbalance": (
                {
                    "is_computed": self.phase_imbalance.is_computed,
                    "voltage_unbalance_factor_vuf": serialize_measurement(self.phase_imbalance.voltage_unbalance_factor_vuf),
                    "phase_voltage_unbalance_rate_pvur": serialize_measurement(self.phase_imbalance.phase_voltage_unbalance_rate_pvur),
                    "current_unbalance_factor_cuf": serialize_measurement(self.phase_imbalance.current_unbalance_factor_cuf),
                    "neutral_current_a": serialize_measurement(self.phase_imbalance.neutral_current_a),
                    "derating_factor_pu": serialize_measurement(self.phase_imbalance.derating_factor_pu),
                }
                if self.phase_imbalance
                else None
            ),
            "anomaly_assessment": (
                {
                    "is_computed": self.anomaly_assessment.is_computed,
                    "anomaly_detected": self.anomaly_assessment.anomaly_detected,
                    "anomaly_score": serialize_measurement(self.anomaly_assessment.anomaly_score),
                    "drift_detected": self.anomaly_assessment.drift_detected,
                    "drift_score": serialize_measurement(self.anomaly_assessment.drift_score),
                    "flagged_dimensions": self.anomaly_assessment.flagged_dimensions,
                    "confidence": self.anomaly_assessment.confidence,
                }
                if self.anomaly_assessment
                else None
            ),
            "decision_intelligence": (
                {
                    "is_computed": self.decision_intelligence.is_computed,
                    "health_index": serialize_measurement(self.decision_intelligence.health_index),
                    "risk_category": self.decision_intelligence.risk_category,
                    "action_urgency": self.decision_intelligence.action_urgency,
                    "active_limit_violations": self.decision_intelligence.active_limit_violations,
                    "recommendations": self.decision_intelligence.recommendations,
                }
                if self.decision_intelligence
                else None
            ),
            "issues": [
                {
                    "stage": issue.stage,
                    "severity": issue.severity.value,
                    "code": issue.code,
                    "message": issue.message,
                    "field_name": issue.field_name,
                    "timestamp": issue.timestamp.isoformat(),
                }
                for issue in self.issues
            ],
        }
