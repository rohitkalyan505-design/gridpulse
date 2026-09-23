"""
GridPulse — Electrical Features & Loading Module Contracts
Boundary contracts for electrical calculations and transformer loading analysis.
References shared contracts from scientific.contracts.
"""

from dataclasses import dataclass
from typing import Optional

from scientific.contracts.asset import TransformerAssetSpec
from scientific.contracts.results import (
    ElectricalFeaturesResult,
    TransformerLoadingResult,
)
from scientific.validation.contracts import ValidatedTelemetryBatch


@dataclass(frozen=True)
class ElectricalCalculationInput:
    """
    Contract defining input requirements for electrical calculations.
    Requires validated telemetry batch and transformer asset nameplate specification.
    """
    telemetry_batch: ValidatedTelemetryBatch
    asset_spec: TransformerAssetSpec


@dataclass(frozen=True)
class TransformerLoadingInput:
    """
    Contract defining input requirements for transformer loading analysis.
    Requires electrical features output and transformer asset specification.
    """
    features: ElectricalFeaturesResult
    asset_spec: TransformerAssetSpec
