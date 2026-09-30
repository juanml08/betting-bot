"""Orquesta el pipeline completo: datos -> features -> modelo -> probabilidad
-> cuota -> probabilidad implicita -> value/edge -> filtros -> riesgo ->
oportunidad.

No decide ni ejecuta nada por si mismo: produce una lista de oportunidades
candidatas junto con un stake sugerido, para que un humano revise y decida
manualmente si apostar.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
from app.opportunities.slot import SlotKey, normalize_slot_text
from app.processing.cleaners import clean_events
from app.valuation.value_calculator import ValueCalculator


@dataclass
class OpportunityCandidate:
    opportunity: ValueOpportunity
    suggested_stake: float
    # Cuando el proveedor observo la cuota (no cuando se persiste).
    captured_at: datetime | None = None


@dataclass(frozen=True)
class ObservedSlot:
    """Slot evaluado en la pasada que NO produjo una candidata valida.
    key.event_ref es el external_id del evento."""

    key: SlotKey
    captured_at: datetime


@dataclass
class OpportunityObservation:
    """Resultado completo de una pasada del pipeline.

    Ademas de las candidatas, reporta lo observado que no califico y los
    eventos evaluados (con el instante de su observacion), para que el
    lifecycle pueda cerrar una candidata anterior que dejo de calificar o
    cuyo slot ya no aparece, sin depender solo del TTL.
    """

    candidates: list[OpportunityCandidate] = field(default_factory=list)
    non_qualifying: list[ObservedSlot] = field(default_factory=list)
    evaluated_events: dict[str, datetime] = field(default_factory=dict)


class OpportunityService:
    def __init__(
        self,
        data_provider: DataProvider,
        odds_provider: OddsProvider,
        probability_model: ProbabilityModel,
        opportunity_filter: OpportunityFilter,
        risk_manager: RiskManager,
        value_calculator: ValueCalculator | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self._data_provider = data_provider
        self._odds_provider = odds_provider
        self._probability_model = probability_model
        self._opportunity_filter = opportunity_filter
        self._risk_manager = risk_manager
        self._value_calculator = value_calculator or ValueCalculator()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def generate_opportunities(self, current_bankroll: float) -> list[OpportunityCandidate]:
        """Solo las candidatas de la pasada (ver generate_observation)."""
        return self.generate_observation(current_bankroll).candidates

    def generate_observation(self, current_bankroll: float) -> OpportunityObservation:
        all_events = clean_events(self._data_provider.get_events())
        target_events = [e for e in all_events if e.status == EventStatus.SCHEDULED]

        observation = OpportunityObservation()
        for event in target_events:
            self._evaluate_event(event, all_events, current_bankroll, observation)
        return observation

    def _evaluate_event(
        self,
        event: MatchEvent,
        history: list[MatchEvent],
        current_bankroll: float,
        observation: OpportunityObservation,
    ) -> None:
        quotes = self._odds_provider.get_odds(event.external_id)
        # Instante de observacion del evento: la cuota mas reciente que trajo el
        # proveedor (o el reloj si no trajo ninguna). Se usa para cerrar slots
        # que ya no aparecen.
        observation.evaluated_events[event.external_id] = (
            max(q.captured_at for q in quotes) if quotes else self._clock()
        )
        if not quotes:
            return

        features = build_features(event, history)

        # La identidad del bookmaker se normaliza aqui igual que en persistencia
        # (SlotKey), para que "Bet365" y " bet365 " formen un solo mercado.
        quotes_sorted = sorted(
            quotes, key=lambda q: (q.market_type, normalize_slot_text(q.bookmaker))
        )
        for (market_type, _), group_iter in groupby(
            quotes_sorted, key=lambda q: (q.market_type, normalize_slot_text(q.bookmaker))
        ):
            market_quotes = list(group_iter)
            estimates = self._probability_model.estimate(event, market_type, features)
            quotes_by_selection = {normalize_slot_text(q.selection): q for q in market_quotes}

            for estimate in estimates:
                quote = quotes_by_selection.get(normalize_slot_text(estimate.selection))
                if quote is None:
                    continue

                opportunity = self._value_calculator.calculate(estimate, quote, market_quotes)
                if not self._opportunity_filter.passes(opportunity):
                    observation.non_qualifying.append(
                        ObservedSlot(
                            SlotKey.of(
                                event.external_id,
                                opportunity.market_type,
                                opportunity.selection,
                                opportunity.bookmaker,
                            ),
                            quote.captured_at,
                        )
                    )
                    continue

                stake = self._risk_manager.suggest_stake(opportunity, current_bankroll)
                observation.candidates.append(
                    OpportunityCandidate(
                        opportunity=opportunity,
                        suggested_stake=stake,
                        captured_at=quote.captured_at,
                    )
                )
