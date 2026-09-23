"""
GridPulse — Provenance, Traceability & Assumption Representation
Part of scientific.contracts (Source of Truth)

Defines:
1. EngineeringAssumption: Explicit representation of parameters, values, and rationales
   when direct telemetry is missing or unmetered.
2. ProvenanceMetadata: End-to-end execution traceability including pipeline version,
   cryptographic telemetry digest (SHA-256), standards references, and evidence breakdown.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, List, Optional

from scientific.contracts.standards import StandardReference


@dataclass(frozen=True)
class EngineeringAssumption:
    """
    Explicit representation of an engineering assumption introduced during processing.

    Scientific Mandate:
    Missing telemetry must never be substituted silently. If an unmetered value
    (e.g., ambient temperature or cooling mode) is assumed, it must be documented
    using this structure with its rationale, standard reference, and sensitivity impact.
    """
    parameter_name: str
    assumed_value: Any
    unit: str
    rationale: str
    standard_reference: Optional[StandardReference] = None
    sensitivity_impact: str = "MEDIUM"  # "HIGH", "MEDIUM", "LOW"

    def __post_init__(self) -> None:
        if not self.parameter_name or not self.parameter_name.strip():
            raise ValueError("parameter_name must be non-empty.")
        if not self.rationale or not self.rationale.strip():
            raise ValueError("rationale must be non-empty.")
        if self.sensitivity_impact not in ("HIGH", "MEDIUM", "LOW"):
            raise ValueError(f"sensitivity_impact must be HIGH, MEDIUM, or LOW, got '{self.sensitivity_impact}'.")


@dataclass(frozen=True)
class ProvenanceMetadata:
    """
    Cryptographic and operational provenance metadata for a scientific run.
    Guarantees that every scientific output can be reproduced deterministically.

    Attributes:
        pipeline_version: Version identifier of the scientific engine.
        execution_timestamp: Time of execution in UTC.
        telemetry_digest: SHA-256 cryptographic hex digest of the input telemetry payload.
        asset_id: Asset identifier associated with the run.
        standards_referenced: List of standard references associated with the run.
        assumptions_applied: Complete list of engineering assumptions applied during the run.
        evidence_tally: Count of results by EvidenceClassification.
    """
    pipeline_version: str
    execution_timestamp: datetime
    telemetry_digest: str
    asset_id: str
    standards_referenced: List[StandardReference] = field(default_factory=list)
    assumptions_applied: List[EngineeringAssumption] = field(default_factory=list)
    evidence_tally: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.pipeline_version or not self.pipeline_version.strip():
            raise ValueError("pipeline_version must be non-empty.")
        if not self.telemetry_digest or len(self.telemetry_digest) != 64:
            raise ValueError("telemetry_digest must be a valid 64-character SHA-256 hex string.")
        if not self.asset_id or not self.asset_id.strip():
            raise ValueError("asset_id must be non-empty.")
        if self.execution_timestamp.tzinfo is None:
            raise ValueError("execution_timestamp must be timezone-aware (strictly UTC).")


def compute_telemetry_digest(raw_bytes: bytes) -> str:
    """Computes a standard SHA-256 hex digest for an input byte payload or string."""
    return hashlib.sha256(raw_bytes).hexdigest()
