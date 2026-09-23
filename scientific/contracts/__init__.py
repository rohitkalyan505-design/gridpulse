"""
GridPulse — Shared Scientific Contracts (Source of Truth)

All modules in scientific/ import their baseline contracts, enumerations,
measurements, and result schemas from this package.
"""

from scientific.contracts.enums import (
    EvidenceClassification,
    MeasurementQuality,
    IssueSeverity,
    CoolingType,
    InsulationClass,
    WindingMaterial,
    PhaseIdentification,
)
from scientific.contracts.standards import StandardReference
from scientific.contracts.measurement import (
    Measurement,
    UnitMetadata,
    CANONICAL_UNITS,
)
from scientific.contracts.asset import (
    TransformerAssetSpec,
    OperationalLimits,
)
from scientific.contracts.provenance import (
    EngineeringAssumption,
    ProvenanceMetadata,
    compute_telemetry_digest,
)
from scientific.contracts.issues import (
    ProcessingIssue,
    ScientificEngineError,
    TelemetryValidationError,
    PhysicalBoundaryError,
    InsufficientTelemetryError,
    ContractViolationError,
    AssetSpecError,
)
from scientific.contracts.results import (
    ValidationSummary,
    ElectricalFeaturesResult,
    TransformerLoadingResult,
    ThermalStateResult,
    PhaseImbalanceResult,
    AnomalyAssessmentResult,
    AssetDecisionResult,
    ScientificRunResult,
)

__all__ = [
    # Enums
    "EvidenceClassification",
    "MeasurementQuality",
    "IssueSeverity",
    "CoolingType",
    "InsulationClass",
    "WindingMaterial",
    "PhaseIdentification",
    # Standards
    "StandardReference",
    # Measurement & Units
    "Measurement",
    "UnitMetadata",
    "CANONICAL_UNITS",
    # Asset
    "TransformerAssetSpec",
    "OperationalLimits",
    # Provenance
    "EngineeringAssumption",
    "ProvenanceMetadata",
    "compute_telemetry_digest",
    # Issues & Exceptions
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
