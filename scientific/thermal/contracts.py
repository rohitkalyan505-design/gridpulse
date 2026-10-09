"""
GridPulse — Thermal Analysis Module Contracts
Part of scientific.thermal.

Boundary contracts for transformer thermal dynamics and insulation degradation.
Phase 2 Step 5: Complete Scientific Contracts (v2.5.0 Specification).
Enforces:
1. ParameterSourceClass provenance for all physical thermal parameters.
2. Mandatory explicit ThermalModelStandard (IEEE vs IEC) with zero defaults.
3. Mandatory explicit AgingStandardPreference (IEEE vs IEC) with zero defaults.
4. Rigid validation rejecting generic engineering assumptions for high-consequence calculations.
5. Forward-interval semantics and typed inputs/results.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from scientific.contracts.asset import TransformerAssetSpec
from scientific.contracts.enums import (
    AgingStandardPreference,
    EvidenceClassification,
    InsulationSystemType,
    IssueSeverity,
    MeasurementQuality,
    ParameterSourceClass,
    ThermalModelStandard,
)
from scientific.contracts.issues import (
    ERR_INVALID_EXPONENT_RANGE,
    ERR_INVALID_PARAMETER_VALUE,
    ERR_UNVALIDATED_THERMAL_PARAMETERS,
    ProcessingIssue,
)
from scientific.contracts.measurement import Measurement
from scientific.contracts.results import (
    ElectricalFeaturesResult,
    ThermalIntervalResult,
    ThermalStateResult,
    TransformerLoadingResult,
)


@dataclass(frozen=True)
class ProvenancedParameter:
    """
    Encapsulates a single engineering thermal parameter with immutable provenance.
    Enforces that high-consequence modeled calculations only consume parameters
    derived from verified test documentation or verified asset records.
    """
    parameter_name: str
    value: float
    unit: str
    source_class: ParameterSourceClass
    reference_document: str
    is_verified: bool
    applicable_asset_id: str
    validity_conditions: Dict[str, Any] = field(default_factory=dict)

    def is_approved_for_high_consequence(self) -> bool:
        """
        Returns True only if the parameter originates from an approved verified source.
        ENGINEERING_ASSUMPTION and UNKNOWN are strictly rejected.
        """
        return self.is_verified and self.source_class in {
            ParameterSourceClass.FACTORY_TEST,
            ParameterSourceClass.MANUFACTURER_DOCUMENT,
            ParameterSourceClass.ASSET_VERIFIED,
        }


@dataclass(frozen=True)
class ThermalModelParameters:
    """
    Physical parameters required for thermal differential models (IEEE C57.91 / IEC 60076-7).
    All fields are backed by ProvenancedParameter records.
    """
    rated_top_oil_rise_k: ProvenancedParameter
    loss_ratio_r: ProvenancedParameter
    oil_exponent_x: ProvenancedParameter
    time_constant_oil_hours: ProvenancedParameter
    time_constant_winding_hours: ProvenancedParameter
    winding_exponent_y: ProvenancedParameter  # IEEE: y_ieee in K^(2y) | IEC: y_iec in K^y
    rated_hot_spot_rise_k: Optional[ProvenancedParameter] = None  # IEEE delta_theta_hs_rated or IEC H*g
    hot_spot_factor_h: Optional[ProvenancedParameter] = None       # IEC H factor
    winding_to_oil_gradient_g: Optional[ProvenancedParameter] = None  # IEC g_rated in K
    reference_life_hours: Optional[ProvenancedParameter] = None

    def validate_for_high_consequence(
        self,
        model_standard: ThermalModelStandard,
        stage: str = "thermal_parameter_validation",
    ) -> List[ProcessingIssue]:
        """
        Validates all mandatory thermal parameters against high-consequence requirements
        and model-specific engineering formulations.
        """
        issues: List[ProcessingIssue] = []

        # Common mandatory parameters
        mandatory_params = [
            self.rated_top_oil_rise_k,
            self.loss_ratio_r,
            self.oil_exponent_x,
            self.time_constant_oil_hours,
            self.time_constant_winding_hours,
            self.winding_exponent_y,
        ]

        # Model-specific parameters
        if model_standard == ThermalModelStandard.IEEE:
            if self.rated_hot_spot_rise_k is None:
                issues.append(
                    ProcessingIssue(
                        stage=stage,
                        severity=IssueSeverity.CRITICAL,
                        code=ERR_UNVALIDATED_THERMAL_PARAMETERS,
                        message="IEEE thermal model profile requires 'rated_hot_spot_rise_k'.",
                        field_name="rated_hot_spot_rise_k",
                    )
                )
            else:
                mandatory_params.append(self.rated_hot_spot_rise_k)
        elif model_standard == ThermalModelStandard.IEC:
            if self.rated_hot_spot_rise_k is None:
                if self.hot_spot_factor_h is None or self.winding_to_oil_gradient_g is None:
                    issues.append(
                        ProcessingIssue(
                            stage=stage,
                            severity=IssueSeverity.CRITICAL,
                            code=ERR_UNVALIDATED_THERMAL_PARAMETERS,
                            message=(
                                "IEC thermal model profile requires either 'rated_hot_spot_rise_k' "
                                "or both 'hot_spot_factor_h' and 'winding_to_oil_gradient_g'."
                            ),
                            field_name="rated_hot_spot_rise_k",
                        )
                    )
                else:
                    mandatory_params.extend([self.hot_spot_factor_h, self.winding_to_oil_gradient_g])
            else:
                mandatory_params.append(self.rated_hot_spot_rise_k)

        # Check source class and positive value for all required parameters
        for p in mandatory_params:
            if not p.is_approved_for_high_consequence():
                issues.append(
                    ProcessingIssue(
                        stage=stage,
                        severity=IssueSeverity.CRITICAL,
                        code=ERR_UNVALIDATED_THERMAL_PARAMETERS,
                        message=(
                            f"Thermal parameter '{p.parameter_name}' has unapproved source class "
                            f"'{p.source_class.value}' or is_verified=False. Generic engineering "
                            f"assumptions are strictly prohibited for high-consequence thermal calculations."
                        ),
                        field_name=p.parameter_name,
                    )
                )
            if p.value <= 0.0:
                issues.append(
                    ProcessingIssue(
                        stage=stage,
                        severity=IssueSeverity.CRITICAL,
                        code=ERR_INVALID_PARAMETER_VALUE,
                        message=f"Thermal parameter '{p.parameter_name}' value must be positive (got {p.value}).",
                        field_name=p.parameter_name,
                    )
                )

        # Validate standard-specific exponent ranges
        if model_standard == ThermalModelStandard.IEEE:
            # IEEE winding exponent y_ieee in K^(2y): typical 0.8, valid range [0.5, 1.2]
            if not (0.5 <= self.winding_exponent_y.value <= 1.2):
                issues.append(
                    ProcessingIssue(
                        stage=stage,
                        severity=IssueSeverity.CRITICAL,
                        code=ERR_INVALID_EXPONENT_RANGE,
                        message=(
                            f"IEEE winding exponent y={self.winding_exponent_y.value} is outside valid "
                            f"range [0.5, 1.2] (applicable to K^(2y)). Verify parameter mapping."
                        ),
                        field_name="winding_exponent_y",
                    )
                )
        elif model_standard == ThermalModelStandard.IEC:
            # IEC winding exponent y_iec in K^y: typical 1.3 - 1.6, valid range [1.0, 2.2]
            if not (1.0 <= self.winding_exponent_y.value <= 2.2):
                issues.append(
                    ProcessingIssue(
                        stage=stage,
                        severity=IssueSeverity.CRITICAL,
                        code=ERR_INVALID_EXPONENT_RANGE,
                        message=(
                            f"IEC winding exponent y={self.winding_exponent_y.value} is outside valid "
                            f"range [1.0, 2.2] (applicable to K^y). Verify parameter mapping."
                        ),
                        field_name="winding_exponent_y",
                    )
                )

        # Validate optional reference life if supplied
        if self.reference_life_hours is not None:
            if not self.reference_life_hours.is_approved_for_high_consequence():
                issues.append(
                    ProcessingIssue(
                        stage=stage,
                        severity=IssueSeverity.WARNING,
                        code=ERR_UNVALIDATED_THERMAL_PARAMETERS,
                        message=(
                            f"Reference life parameter '{self.reference_life_hours.parameter_name}' "
                            f"has unapproved source class '{self.reference_life_hours.source_class.value}'. "
                            f"Loss-of-life percentage will remain UNKNOWN."
                        ),
                        field_name="reference_life_hours",
                    )
                )
            elif self.reference_life_hours.value <= 0.0:
                issues.append(
                    ProcessingIssue(
                        stage=stage,
                        severity=IssueSeverity.CRITICAL,
                        code=ERR_INVALID_PARAMETER_VALUE,
                        message=(
                            f"Reference life parameter value must be positive "
                            f"(got {self.reference_life_hours.value})."
                        ),
                        field_name="reference_life_hours",
                    )
                )

        return issues


@dataclass(frozen=True)
class ThermalAnalysisInput:
    """
    Contract defining input requirements for transformer thermal and aging analytics.
    Phase 2 Step 5: Forward-interval batch and step processing.
    """
    asset_id: str
    loading_results: List[TransformerLoadingResult]
    thermal_parameters: Optional[ThermalModelParameters]
    insulation_system: InsulationSystemType
    thermal_model_standard: Optional[ThermalModelStandard]  # Mandatory: No default permitted!
    aging_standard: Optional[AgingStandardPreference]       # Mandatory: No default permitted!
    ambient_temperature_series: Optional[List[Optional[float]]] = None
    measured_top_oil_series: Optional[List[Optional[float]]] = None
    measured_hot_spot_series: Optional[List[Optional[float]]] = None
    initial_prior_thermal_state: Optional[ThermalStateResult] = None
    continuity_tolerance_seconds: float = 900.0

    # Backward compatibility attributes
    features: Optional[ElectricalFeaturesResult] = None
    loading: Optional[TransformerLoadingResult] = None
    ambient_temp: Optional[Measurement[float]] = None
    asset_spec: Optional[TransformerAssetSpec] = None
