"""
GridPulse — Decision Intelligence Module Contracts
Boundary contracts for deterministic health indexing, asset risk classification,
and engineering recommendations.
References shared contracts from scientific.contracts.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from scientific.contracts.asset import OperationalLimits, TransformerAssetSpec
from scientific.contracts.results import (
    AnomalyAssessmentResult,
    AssetDecisionResult,
    ElectricalFeaturesResult,
    PhaseImbalanceResult,
    ThermalStateResult,
    TransformerLoadingResult,
)


@dataclass(frozen=True)
class DecisionRuleCriteria:
    """
    Contract defining decision and health index configuration criteria.
    Weightings and thresholds are parameterized rather than hardcoded.
    """
    health_index_scale_min: float = 0.0
    health_index_scale_max: float = 100.0
    critical_risk_threshold: float = 85.0
    high_risk_threshold: float = 70.0
    moderate_risk_threshold: float = 50.0
    criteria_weights: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionIntelligenceInput:
    """
    Contract defining input requirements for the decision intelligence stage.
    Synthesizes upstream deterministic physical metrics and statistical anomaly outputs.
    """
    asset_spec: TransformerAssetSpec
    features: ElectricalFeaturesResult
    loading: TransformerLoadingResult
    thermal: ThermalStateResult
    imbalance: PhaseImbalanceResult
    anomaly: AnomalyAssessmentResult
    operational_limits: OperationalLimits
    rule_criteria: Optional[DecisionRuleCriteria] = None
