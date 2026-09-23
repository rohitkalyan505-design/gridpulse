"""
GridPulse — Scientific Engine
Pure Python numerical, physical, and statistical distribution asset intelligence.

Locked Phase 2 Scientific Pipeline:
Electrical Data
→ Data Validation
→ Electrical Calculations
→ Transformer Loading
→ Thermal Analysis
→ Phase Imbalance
→ Anomaly Detection
→ Decision Intelligence
→ Structured Scientific Results
"""

__version__ = "0.2.0-step1"

from scientific.contracts import (
    EvidenceClassification,
    MeasurementQuality,
    Measurement,
    UnitMetadata,
    CANONICAL_UNITS,
    TransformerAssetSpec,
    OperationalLimits,
    StandardReference,
    EngineeringAssumption,
    ProvenanceMetadata,
    ProcessingIssue,
    ValidationSummary,
    ElectricalFeaturesResult,
    TransformerLoadingResult,
    ThermalStateResult,
    PhaseImbalanceResult,
    AnomalyAssessmentResult,
    AssetDecisionResult,
    ScientificRunResult,
    ScientificEngineError,
    TelemetryValidationError,
    PhysicalBoundaryError,
    InsufficientTelemetryError,
    ContractViolationError,
    AssetSpecError,
)

__all__ = [
    "__version__",
    # Enums
    "EvidenceClassification",
    "MeasurementQuality",
    # Measurement & Units
    "Measurement",
    "UnitMetadata",
    "CANONICAL_UNITS",
    # Asset
    "TransformerAssetSpec",
    "OperationalLimits",
    # Standards & Provenance
    "StandardReference",
    "EngineeringAssumption",
    "ProvenanceMetadata",
    # Issues
    "ProcessingIssue",
    "ScientificEngineError",
    "TelemetryValidationError",
    "PhysicalBoundaryError",
    "InsufficientTelemetryError",
    "ContractViolationError",
    "AssetSpecError",
    # Results
    "ValidationSummary",
    "ElectricalFeaturesResult",
    "TransformerLoadingResult",
    "ThermalStateResult",
    "PhaseImbalanceResult",
    "AnomalyAssessmentResult",
    "AssetDecisionResult",
    "ScientificRunResult",
]
