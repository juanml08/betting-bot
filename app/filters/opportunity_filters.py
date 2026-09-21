"""Etapa FILTROS.

Decide si una ValueOpportunity es lo bastante buena para considerarse
candidata. Los umbrales son configurables (ver app.core.config) y no son
garantia de nada: son un primer filtro de calidad antes de la gestion de
riesgo y la revision manual.
"""

from dataclasses import dataclass

from app.domain.models import ValueOpportunity


@dataclass
class OpportunityFilterConfig:
    min_edge: float
    min_expected_value: float
    min_odds: float
    max_odds: float


class ThresholdOpportunityFilter:
    def __init__(self, config: OpportunityFilterConfig):
        self._config = config

    def passes(self, opportunity: ValueOpportunity) -> bool:
        c = self._config
        return (
            opportunity.edge >= c.min_edge
            and opportunity.expected_value >= c.min_expected_value
            and c.min_odds <= opportunity.odds_value <= c.max_odds
        )
