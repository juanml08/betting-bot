"""Orquesta el pipeline completo: datos -> features -> modelo -> probabilidad
-> cuota -> probabilidad implicita -> value/edge -> filtros -> riesgo ->
oportunidad.

No decide ni ejecuta nada por si mismo: produce una lista de oportunidades
candidatas junto con un stake sugerido, para que un humano revise y decida
manualmente si apostar.
"""

from dataclasses import dataclass
from itertools import groupby

from app.domain.interfaces import (
    DataProvider,
    OddsProvider,
    OpportunityFilter,
    ProbabilityModel,
    RiskManager,
)
from app.domain.models import EventStatus, MatchEvent, ValueOpportunity
from app.features.feature_builder import build_features
from app.processing.cleaners import clean_events
from app.valuation.value_calculator import ValueCalculator


@dataclass
class OpportunityCandidate:
    opportunity: ValueOpportunity
    suggested_stake: float


class OpportunityService:
    def __init__(
        self,
        data_provider: DataProvider,
        odds_provider: OddsProvider,
        probability_model: ProbabilityModel,
        opportunity_filter: OpportunityFilter,
        risk_manager: RiskManager,
        value_calculator: ValueCalculator | None = None,
    ):
        self._data_provider = data_provider
        self._odds_provider = odds_provider
        self._probability_model = probability_model
        self._opportunity_filter = opportunity_filter
        self._risk_manager = risk_manager
        self._value_calculator = value_calculator or ValueCalculator()

    def generate_opportunities(self, current_bankroll: float) -> list[OpportunityCandidate]:
        all_events = clean_events(self._data_provider.get_events())
        target_events = [e for e in all_events if e.status == EventStatus.SCHEDULED]

        candidates: list[OpportunityCandidate] = []
        for event in target_events:
            candidates.extend(self._evaluate_event(event, all_events, current_bankroll))
        return candidates

    def _evaluate_event(
        self, event: MatchEvent, history: list[MatchEvent], current_bankroll: float
    ) -> list[OpportunityCandidate]:
        quotes = self._odds_provider.get_odds(event.external_id)
        if not quotes:
            return []

        features = build_features(event, history)
        candidates: list[OpportunityCandidate] = []

        quotes_sorted = sorted(quotes, key=lambda q: (q.market_type, q.bookmaker))
        for (market_type, bookmaker), group_iter in groupby(
            quotes_sorted, key=lambda q: (q.market_type, q.bookmaker)
        ):
            market_quotes = list(group_iter)
            estimates = self._probability_model.estimate(event, market_type, features)
            quotes_by_selection = {q.selection: q for q in market_quotes}

            for estimate in estimates:
                quote = quotes_by_selection.get(estimate.selection)
                if quote is None:
                    continue

                opportunity = self._value_calculator.calculate(estimate, quote, market_quotes)
                if not self._opportunity_filter.passes(opportunity):
                    continue

                stake = self._risk_manager.suggest_stake(opportunity, current_bankroll)
                candidates.append(OpportunityCandidate(opportunity=opportunity, suggested_stake=stake))

        return candidates
