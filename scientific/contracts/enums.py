"""
GridPulse — Scientific Engine Shared Enumerations
Part of scientific.contracts (Source of Truth)

All scientific enumerations locked for Phase 2:
- EvidenceClassification: The 5-level scientific evidence classification.
- MeasurementQuality: Standardized telemetry quality states.
- IssueSeverity: Severity classification for processing issues.
- Transformer Asset Parameters: Cooling, insulation, winding material, and phases.
"""

from enum import Enum


class EvidenceClassification(str, Enum):
    """
    Locked 5-level scientific evidence classification.
    Every calculated, measured, or derived metric in GridPulse must carry
    one of these explicit evidence tags. Under no circumstances may an
    evidence level be upgraded to a higher level without legitimate physical instrumentation.
    """
    MEASURED = "MEASURED"
    CALCULATED = "CALCULATED"
    MODELED = "MODELED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class MeasurementQuality(str, Enum):
    """
    Standardized telemetry data quality states.
    Applied to individual measurement points to reflect hardware validity,
    communication fidelity, and sanity boundaries.
    """
    GOOD = "GOOD"
    SUSPECT = "SUSPECT"
    BAD = "BAD"
    MISSING = "MISSING"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    CALIBRATION_EXPIRED = "CALIBRATION_EXPIRED"


class IssueSeverity(str, Enum):
    """Severity levels for pipeline diagnostic issues and exceptions."""
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class CoolingType(str, Enum):
    """Standard transformer cooling classes (IEC 60076 / IEEE C57)."""
    ONAN = "ONAN"  # Oil Natural Air Natural
    ONAF = "ONAF"  # Oil Natural Air Forced
    OFAF = "OFAF"  # Oil Forced Air Forced
    OFWF = "OFWF"  # Oil Forced Water Forced
    AN = "AN"      # Dry-type Air Natural
    AF = "AF"      # Dry-type Air Forced


class InsulationClass(str, Enum):
    """Thermal insulation classes defining temperature index (IEC / IEEE)."""
    CLASS_A_105 = "CLASS_A_105"  # 105°C (Standard mineral oil immersed)
    CLASS_E_120 = "CLASS_E_120"  # 120°C
    CLASS_B_130 = "CLASS_B_130"  # 130°C
    CLASS_F_155 = "CLASS_F_155"  # 155°C
    CLASS_H_180 = "CLASS_H_180"  # 180°C


class WindingMaterial(str, Enum):
    """Conductor material for transformer windings."""
    COPPER = "COPPER"
    ALUMINUM = "ALUMINUM"


class PhaseIdentification(str, Enum):
    """Phase identification for multi-phase electrical networks."""
    PHASE_A = "A"
    PHASE_B = "B"
    PHASE_C = "C"
    NEUTRAL = "N"
    THREE_PHASE = "3P"
