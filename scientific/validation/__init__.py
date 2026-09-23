"""
GridPulse — Validation Module
Telemetry validation engine, boundary rules, sanity conventions, and quality tagging.
"""

from scientific.validation.contracts import (
    PhysicalBoundaryRule,
    ValidatedTelemetryBatch,
    ValidatedTelemetryRecord,
)
from scientific.validation.engine import TelemetryValidator
from scientific.validation.rules import (
    ALLOWED_UNITS_BY_TYPE,
    CHANNEL_TAG_ALIASES,
    DEFAULT_FLATLINE_THRESHOLDS,
    DEFAULT_SANITY_LIMITS,
    FlatlineThreshold,
    GenericSanityLimits,
    MeasurementType,
    ValidationConfig,
)

__all__ = [
    # Contracts
    "PhysicalBoundaryRule",
    "ValidatedTelemetryRecord",
    "ValidatedTelemetryBatch",
    # Engine & Rules
    "TelemetryValidator",
    "ValidationConfig",
    "MeasurementType",
    "GenericSanityLimits",
    "FlatlineThreshold",
    "DEFAULT_SANITY_LIMITS",
    "DEFAULT_FLATLINE_THRESHOLDS",
    "ALLOWED_UNITS_BY_TYPE",
    "CHANNEL_TAG_ALIASES",
]
