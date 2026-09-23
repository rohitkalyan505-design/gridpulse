"""
GridPulse — Anomaly Detection Module Contracts
Boundary contracts for statistical anomaly detection, baseline drift,
and out-of-distribution observation.
References shared contracts from scientific.contracts.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from scientific.contracts.results import (
    AnomalyAssessmentResult,
    ElectricalFeaturesResult,
    PhaseImbalanceResult,
    TransformerLoadingResult,
)


@dataclass(frozen=True)
class AnomalyBaselineSpec:
    """
    Contract defining statistical baseline specification for an asset.
    Represents historical parameters without running ML training in Step 1.
    """
    baseline_id: str
    asset_id: str
    feature_names: List[str] = field(default_factory=list)
    anomaly_threshold: float = 3.0  # e.g., 3-sigma or distance threshold
    drift_sensitivity: float = 0.05
    model_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnomalyDetectionInput:
    """
    Contract defining input requirements for anomaly detection.
    Consumes upstream physical features, loading, and imbalance along with baseline.
    """
    features: ElectricalFeaturesResult
    loading: TransformerLoadingResult
    imbalance: PhaseImbalanceResult
    baseline_spec: Optional[AnomalyBaselineSpec] = None
