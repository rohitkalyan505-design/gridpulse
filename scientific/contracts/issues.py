"""
GridPulse — Diagnostic Issues & Scientific Exceptions
Part of scientific.contracts (Source of Truth)

Defines:
1. ProcessingIssue: Structured diagnostics, alerts, and warnings collected during
   pipeline execution without crashing fault-tolerant operations.
2. Scientific Engine Exceptions: Formal typed exception hierarchy for strict
   validation and contract violations.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from scientific.contracts.enums import IssueSeverity


@dataclass(frozen=True)
class ProcessingIssue:
    """
    Structured issue recorded during scientific pipeline execution.
    Preserves diagnostic context when handling degraded or invalid telemetry.
    """
    stage: str
    severity: IssueSeverity
    code: str
    message: str
    field_name: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self) -> None:
        if not self.stage or not self.stage.strip():
            raise ValueError("stage must be non-empty.")
        if not self.code or not self.code.strip():
            raise ValueError("code must be non-empty.")
        if not self.message or not self.message.strip():
            raise ValueError("message must be non-empty.")
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", datetime.now(timezone.utc))
        elif self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=timezone.utc))


# ==============================================================================
# Domain Exception Hierarchy
# ==============================================================================

class ScientificEngineError(Exception):
    """Base exception for all GridPulse Scientific Engine errors."""
    pass


class TelemetryValidationError(ScientificEngineError):
    """Raised when raw telemetry fails schema, formatting, or parsing rules."""
    pass


class PhysicalBoundaryError(ScientificEngineError):
    """Raised when telemetry or computed quantities violate immutable physical laws."""
    pass


class InsufficientTelemetryError(ScientificEngineError):
    """Raised when observable telemetry is insufficient to compute an engineering metric."""
    pass


class ContractViolationError(ScientificEngineError):
    """Raised when data passed between scientific modules violates pipeline contracts."""
    pass


class AssetSpecError(ScientificEngineError):
    """Raised when a transformer asset specification is invalid or physically impossible."""
    pass
