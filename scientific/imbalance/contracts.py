"""
GridPulse — Phase Imbalance Module Contracts
Boundary contracts for three-phase asymmetrical loading, symmetrical component
unbalance ratios, neutral current analysis, and evidence-grounded derating.
Part of Phase 2 Step 6.
"""

from dataclasses import dataclass, field
from datetime import datetime
import math
from typing import Any, Dict, List, Optional, Union

from scientific.contracts.asset import OperationalLimits, TransformerAssetSpec
from scientific.contracts.enums import (
    DeratingMethod,
    EvidenceClassification,
    MeasurementQuality,
    ParameterSourceClass,
    PhaseIdentification,
    PhaseSequence,
    PhasorAngleConvention,
)
from scientific.contracts.measurement import Measurement
from scientific.contracts.results import (
    ElectricalFeaturesResult,
    TransformerLoadingResult,
)


@dataclass(frozen=True)
class ComplexPhasor:
    """
    Deterministic representation of an AC complex phasor.
    Expresses RMS magnitude and phase angle under a documented angle reference convention.
    """
    real: float
    imag: float
    magnitude: float
    angle_deg: float
    angle_rad: float
    unit: str
    angle_convention: PhasorAngleConvention = PhasorAngleConvention.COSINE_REFERENCE

    def __post_init__(self) -> None:
        if not math.isfinite(self.real) or not math.isfinite(self.imag):
            raise ValueError(f"Phasor components must be finite: real={self.real}, imag={self.imag}.")
        if self.magnitude < 0 or not math.isfinite(self.magnitude):
            raise ValueError(f"Phasor magnitude must be non-negative and finite, got {self.magnitude}.")
        if not math.isfinite(self.angle_deg) or not math.isfinite(self.angle_rad):
            raise ValueError("Phasor angle must be finite.")

    @property
    def as_complex(self) -> complex:
        """Returns Python standard complex number."""
        return complex(self.real, self.imag)

    @classmethod
    def from_polar(
        cls,
        magnitude: float,
        angle_deg: float,
        unit: str,
        angle_convention: PhasorAngleConvention = PhasorAngleConvention.COSINE_REFERENCE,
    ) -> "ComplexPhasor":
        """Constructs a ComplexPhasor from RMS magnitude and angle in degrees."""
        if not math.isfinite(magnitude) or magnitude < 0.0:
            raise ValueError(f"Magnitude must be non-negative and finite, got {magnitude}.")
        if not math.isfinite(angle_deg):
            raise ValueError(f"Angle must be finite, got {angle_deg}.")

        # Wrap angle_deg to [-180, 180]
        wrapped_deg = ((angle_deg + 180.0) % 360.0) - 180.0
        angle_rad = math.radians(wrapped_deg)
        real = magnitude * math.cos(angle_rad)
        imag = magnitude * math.sin(angle_rad)

        return cls(
            real=real,
            imag=imag,
            magnitude=magnitude,
            angle_deg=wrapped_deg,
            angle_rad=angle_rad,
            unit=unit,
            angle_convention=angle_convention,
        )

    @classmethod
    def from_complex(
        cls,
        val: complex,
        unit: str,
        angle_convention: PhasorAngleConvention = PhasorAngleConvention.COSINE_REFERENCE,
    ) -> "ComplexPhasor":
        """Constructs a ComplexPhasor from a Python complex number."""
        if not math.isfinite(val.real) or not math.isfinite(val.imag):
            raise ValueError(f"Complex values must be finite, got {val}.")

        magnitude = abs(val)
        angle_rad = math.atan2(val.imag, val.real)
        angle_deg = math.degrees(angle_rad)

        return cls(
            real=val.real,
            imag=val.imag,
            magnitude=magnitude,
            angle_deg=angle_deg,
            angle_rad=angle_rad,
            unit=unit,
            angle_convention=angle_convention,
        )


@dataclass(frozen=True)
class PhaseQuantity:
    """
    Representation of a single phase's electrical measurement.
    Preserves phase identity, magnitude, optional angle, quality, and provenance.
    """
    phase: PhaseIdentification
    magnitude: Measurement[float]
    angle_deg: Optional[Measurement[float]] = None
    angle_convention: PhasorAngleConvention = PhasorAngleConvention.COSINE_REFERENCE

    def __post_init__(self) -> None:
        if self.phase not in (
            PhaseIdentification.PHASE_A,
            PhaseIdentification.PHASE_B,
            PhaseIdentification.PHASE_C,
            PhaseIdentification.NEUTRAL,
        ):
            raise ValueError(f"Invalid phase identification: {self.phase}.")

    @property
    def is_phasor(self) -> bool:
        """True if both valid magnitude and valid angle exist."""
        return (
            self.magnitude is not None
            and self.magnitude.value is not None
            and math.isfinite(self.magnitude.value)
            and self.magnitude.value >= 0.0
            and self.angle_deg is not None
            and self.angle_deg.value is not None
            and math.isfinite(self.angle_deg.value)
        )

    @property
    def timestamp(self) -> datetime:
        return self.magnitude.timestamp

    @property
    def unit(self) -> str:
        return self.magnitude.unit

    @property
    def quality(self) -> MeasurementQuality:
        if self.angle_deg is not None and self.angle_deg.quality == MeasurementQuality.SUSPECT:
            return MeasurementQuality.SUSPECT
        return self.magnitude.quality

    @property
    def evidence(self) -> EvidenceClassification:
        return self.magnitude.evidence

    def to_complex_phasor(self) -> Optional[ComplexPhasor]:
        """Converts to ComplexPhasor if valid angle and magnitude exist, otherwise None."""
        if not self.is_phasor:
            return None
        return ComplexPhasor.from_polar(
            magnitude=self.magnitude.value,
            angle_deg=self.angle_deg.value,
            unit=self.magnitude.unit,
            angle_convention=self.angle_convention,
        )


@dataclass(frozen=True)
class ThreePhaseQuantity:
    """
    Validated container for three-phase quantities (voltage or current) at a single observation time.
    """
    phase_a: PhaseQuantity
    phase_b: PhaseQuantity
    phase_c: PhaseQuantity
    neutral: Optional[PhaseQuantity] = None
    phase_sequence: PhaseSequence = PhaseSequence.ABC
    asset_id: str = ""
    timestamp: Optional[datetime] = None

    def __post_init__(self) -> None:
        # Verify phase identity matching
        if self.phase_a.phase != PhaseIdentification.PHASE_A:
            raise ValueError(f"phase_a must have identity PHASE_A, got {self.phase_a.phase}.")
        if self.phase_b.phase != PhaseIdentification.PHASE_B:
            raise ValueError(f"phase_b must have identity PHASE_B, got {self.phase_b.phase}.")
        if self.phase_c.phase != PhaseIdentification.PHASE_C:
            raise ValueError(f"phase_c must have identity PHASE_C, got {self.phase_c.phase}.")
        if self.neutral is not None and self.neutral.phase != PhaseIdentification.NEUTRAL:
            raise ValueError(f"neutral must have identity NEUTRAL, got {self.neutral.phase}.")

        ts = self.timestamp or self.phase_a.timestamp
        if ts.tzinfo is None:
            raise ValueError("ThreePhaseQuantity timestamp must be timezone-aware (strictly UTC).")

    @property
    def has_complex_phasors(self) -> bool:
        """True only when all three phases have valid, finite magnitude and angle."""
        return self.phase_a.is_phasor and self.phase_b.is_phasor and self.phase_c.is_phasor

    @property
    def is_complete_three_phase(self) -> bool:
        """True when all three phase magnitudes are non-null, finite, and non-negative."""
        for p in (self.phase_a, self.phase_b, self.phase_c):
            if (
                p.magnitude is None
                or p.magnitude.value is None
                or not math.isfinite(p.magnitude.value)
                or p.magnitude.value < 0.0
            ):
                return False
        return True

    @classmethod
    def from_measurements(
        cls,
        va: Measurement[float],
        vb: Measurement[float],
        vc: Measurement[float],
        asset_id: str,
        timestamp: Optional[datetime] = None,
        phase_sequence: PhaseSequence = PhaseSequence.ABC,
        neutral: Optional[Measurement[float]] = None,
    ) -> "ThreePhaseQuantity":
        """Constructs magnitude-only ThreePhaseQuantity from raw phase measurements."""
        ts = timestamp or va.timestamp
        q_a = PhaseQuantity(phase=PhaseIdentification.PHASE_A, magnitude=va)
        q_b = PhaseQuantity(phase=PhaseIdentification.PHASE_B, magnitude=vb)
        q_c = PhaseQuantity(phase=PhaseIdentification.PHASE_C, magnitude=vc)
        q_n = (
            PhaseQuantity(phase=PhaseIdentification.NEUTRAL, magnitude=neutral)
            if neutral is not None
            else None
        )
        return cls(
            phase_a=q_a,
            phase_b=q_b,
            phase_c=q_c,
            neutral=q_n,
            phase_sequence=phase_sequence,
            asset_id=asset_id,
            timestamp=ts,
        )

    @classmethod
    def from_phasors(
        cls,
        mag_a: Measurement[float],
        ang_a: Measurement[float],
        mag_b: Measurement[float],
        ang_b: Measurement[float],
        mag_c: Measurement[float],
        ang_c: Measurement[float],
        asset_id: str,
        timestamp: Optional[datetime] = None,
        phase_sequence: PhaseSequence = PhaseSequence.ABC,
        neutral_mag: Optional[Measurement[float]] = None,
        neutral_ang: Optional[Measurement[float]] = None,
    ) -> "ThreePhaseQuantity":
        """Constructs complex phasor ThreePhaseQuantity from magnitudes and angles."""
        ts = timestamp or mag_a.timestamp
        q_a = PhaseQuantity(phase=PhaseIdentification.PHASE_A, magnitude=mag_a, angle_deg=ang_a)
        q_b = PhaseQuantity(phase=PhaseIdentification.PHASE_B, magnitude=mag_b, angle_deg=ang_b)
        q_c = PhaseQuantity(phase=PhaseIdentification.PHASE_C, magnitude=mag_c, angle_deg=ang_c)
        q_n = (
            PhaseQuantity(
                phase=PhaseIdentification.NEUTRAL,
                magnitude=neutral_mag,
                angle_deg=neutral_ang,
            )
            if neutral_mag is not None
            else None
        )
        return cls(
            phase_a=q_a,
            phase_b=q_b,
            phase_c=q_c,
            neutral=q_n,
            phase_sequence=phase_sequence,
            asset_id=asset_id,
            timestamp=ts,
        )


@dataclass(frozen=True)
class PhaseMagnitudeImbalance:
    """
    Deterministic phase magnitude unbalance metrics.
    Calculates arithmetic mean, signed deviations, absolute deviations,
    maximum absolute deviation, and percentage deviation using the documented mean-based denominator.
    Also retains the true maximum phase magnitude.
    """
    quantity_type: str  # "VOLTAGE" or "CURRENT"
    mean_magnitude: Measurement[float]
    deviations_signed: Dict[str, Measurement[float]]
    deviations_absolute: Dict[str, Measurement[float]]
    max_absolute_deviation: Measurement[float]
    max_deviation_percent: Optional[Measurement[float]]
    denominator_definition: str = "THREE_PHASE_ARITHMETIC_MEAN"
    max_phase_magnitude: Optional[Measurement[float]] = None
    is_valid: bool = True


@dataclass(frozen=True)
class ParameterWithProvenance:
    """
    Type-safe representation of an engineering parameter with verifiable provenance.
    Enforces that safety-sensitive derating calculations only consume verified parameters
    originating from approved, verified documentation (e.g., factory test report).
    Bare floats and unverified parameters are strictly rejected.
    """
    parameter_name: str
    value: float
    unit: str
    source_class: Union[ParameterSourceClass, str]
    reference_document: str = ""
    is_verified: bool = False
    applicable_asset_id: str = ""
    validity_conditions: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise ValueError(f"Parameter '{self.parameter_name}' value must be finite, got {self.value}.")

    def is_approved_for_provenance(self) -> bool:
        """
        Returns True only if the parameter originates from an approved verified source.
        ENGINEERING_ASSUMPTION and UNKNOWN are strictly rejected.
        """
        src = (
            self.source_class.value
            if isinstance(self.source_class, ParameterSourceClass)
            else str(self.source_class)
        )
        return self.is_verified and src in {
            ParameterSourceClass.FACTORY_TEST.value,
            ParameterSourceClass.MANUFACTURER_DOCUMENT.value,
            ParameterSourceClass.ASSET_VERIFIED.value,
            "NAMEPLATE",
        }


@dataclass(frozen=True)
class SymmetricalComponentsResult:
    """
    Fortescue symmetrical components result for valid three-phase complex phasors.
    Preserves complex sequence components (X0, X1, X2), magnitudes, sequence ratios,
    neutral current, and reconstruction fidelity.
    """
    quantity_type: str  # "VOLTAGE" or "CURRENT"
    zero_sequence: Optional[ComplexPhasor] = None
    positive_sequence: Optional[ComplexPhasor] = None
    negative_sequence: Optional[ComplexPhasor] = None
    zero_sequence_magnitude: Optional[Measurement[float]] = None
    positive_sequence_magnitude: Optional[Measurement[float]] = None
    negative_sequence_magnitude: Optional[Measurement[float]] = None
    negative_sequence_ratio_percent: Optional[Measurement[float]] = None  # VUF or CUF (|X2|/|X1| * 100)
    zero_sequence_ratio_percent: Optional[Measurement[float]] = None      # |X0|/|X1| * 100
    neutral_current: Optional[ComplexPhasor] = None                       # In = -3 * I0 (for currents)
    neutral_current_magnitude: Optional[Measurement[float]] = None
    phase_sequence: PhaseSequence = PhaseSequence.ABC
    reconstruction_max_error: Optional[float] = None
    is_valid: bool = True
    evidence: EvidenceClassification = EvidenceClassification.CALCULATED


@dataclass(frozen=True)
class DeratingConfiguration:
    """
    Configuration parameters for transformer derating under unbalanced loading.
    Requires explicit method selection and verified asset parameters.
    Bare floats and unverified parameter inputs are strictly rejected.
    """
    method: DeratingMethod = DeratingMethod.MAX_PHASE_CURRENT_CAPACITY
    loss_ratio_r: Optional[ParameterWithProvenance] = None  # Load loss to no-load loss ratio
    eddy_loss_factor_pec: Optional[ParameterWithProvenance] = None  # Winding eddy current loss factor
    manufacturer_curve_points: Optional[Dict[float, float]] = None

    def __post_init__(self) -> None:
        if self.loss_ratio_r is not None and not isinstance(self.loss_ratio_r, ParameterWithProvenance):
            raise TypeError(
                f"loss_ratio_r must be an instance of ParameterWithProvenance or None, "
                f"got {type(self.loss_ratio_r).__name__}. Bare floats are prohibited."
            )
        if self.eddy_loss_factor_pec is not None and not isinstance(self.eddy_loss_factor_pec, ParameterWithProvenance):
            raise TypeError(
                f"eddy_loss_factor_pec must be an instance of ParameterWithProvenance or None, "
                f"got {type(self.eddy_loss_factor_pec).__name__}. Bare floats are prohibited."
            )


@dataclass(frozen=True)
class DeratingAssessmentResult:
    """
    Evidence-grounded transformer derating result under unbalanced loading.
    Separates measured quantities, deterministic calculations, and engineering recommendations.
    """
    derating_factor_pu: Optional[Measurement[float]] = None
    method_applied: DeratingMethod = DeratingMethod.NONE
    is_derated: bool = False
    status: str = "UNKNOWN"  # "CALCULATED", "UNKNOWN", "NOT_REQUIRED", "UNVERIFIED"
    applicability_notes: str = ""
    limitations: str = ""
    engineering_recommendations: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PhaseImbalanceInput:
    """
    Contract defining input requirements for phase unbalance and derating calculations.
    Requires electrical features, transformer loading, and asset spec.
    Optionally accepts explicit ThreePhaseQuantity structures and derating configuration.
    """
    features: ElectricalFeaturesResult
    loading: TransformerLoadingResult
    asset_spec: TransformerAssetSpec
    operational_limits: Optional[OperationalLimits] = None
    voltage_three_phase: Optional[ThreePhaseQuantity] = None
    current_three_phase: Optional[ThreePhaseQuantity] = None
    derating_config: Optional[DeratingConfiguration] = None
