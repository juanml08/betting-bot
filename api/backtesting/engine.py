"""Motor de backtesting: reproduce el pipeline sobre eventos historicos ya
finalizados, respetando el orden temporal (solo se usa historia estrictamente
anterior al evento evaluado, para evitar look-ahead bias).

El objetivo NO es demostrar que una estrategia es rentable por diseno, sino
darle a la etapa de EVALUACION DE LA ESTRATEGIA datos objetivos (ROI, hit
rate, calibracion) con los que aceptarla o descartarla.
"""

from dataclasses import dataclass, field
from datetime import date

from app.domain.interfaces import (
    DataProvider,
    OddsProvider,
    OpportunityFilter,
    ProbabilityModel,
    RiskManager,
)
from app.domain.models import MatchEvent
from app.features.feature_builder import build_features
from app.processing.cleaners import clean_events
from app.valuation.value_calculator import ValueCalculator

_RESULT_TO_SELECTION = {
    "home_win": "home",
    "away_win": "away",
    "draw": "draw",
}


@dataclass
class BacktestBetRecord:
    event_external_id: str
    market_type: str
    selection: str
    odds_value: float
    estimated_probability: float
    stake: float
    won: bool
    profit: float
    bankroll_after: float


@dataclass
class BacktestReport:
    initial_bankroll: float
    final_bankroll: float
    records: list[BacktestBetRecord] = field(default_factory=list)


class BacktestEngine:
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

    def run(self, *, initial_bankroll: float, date_from: date, date_to: date) -> BacktestReport:
        all_events = clean_events(self._data_provider.get_events())
        finished_events = sorted(
            (
                e
                for e in all_events
                if e.status == "finished"
                and e.result is not None
                and date_from <= e.start_time.date() <= date_to
            ),
            key=lambda e: e.start_time,
        )

        bankroll = initial_bankroll
        records: list[BacktestBetRecord] = []

        for event in finished_events:
            history = [e for e in all_events if e.start_time < event.start_time]
            bankroll, new_records = self._evaluate_event(event, history, bankroll)
            records.extend(new_records)

        return BacktestReport(initial_bankroll=initial_bankroll, final_bankroll=bankroll, records=records)

    def _evaluate_event(
        self, event: MatchEvent, history: list[MatchEvent], bankroll: float
    ) -> tuple[float, list[BacktestBetRecord]]:
        quotes = self._odds_provider.get_odds(event.external_id)
        if not quotes:
            return bankroll, []

        features = build_features(event, history)
        winning_selection = _RESULT_TO_SELECTION.get(event.result or "")
        records: list[BacktestBetRecord] = []

        quotes_by_market: dict[tuple[str, str], list] = {}
        for quote in quotes:
            quotes_by_market.setdefault((quote.market_type, quote.bookmaker), []).append(quote)

        for (market_type, _bookmaker), market_quotes in quotes_by_market.items():
            estimates = self._probability_model.estimate(event, market_type, features)
            quotes_by_selection = {q.selection: q for q in market_quotes}

            for estimate in estimates:
                quote = quotes_by_selection.get(estimate.selection)
                if quote is None:
                    continue

                opportunity = self._value_calculator.calculate(estimate, quote, market_quotes)
                if not self._opportunity_filter.passes(opportunity):
                    continue

                stake = self._risk_manager.suggest_stake(opportunity, bankroll)
                if stake <= 0:
                    continue

                won = estimate.selection == winning_selection
                profit = stake * (quote.odds_value - 1.0) if won else -stake
                bankroll += profit

                records.append(
                    BacktestBetRecord(
                        event_external_id=event.external_id,
                        market_type=market_type,
                        selection=estimate.selection,
                        odds_value=quote.odds_value,
                        estimated_probability=estimate.probability,
                        stake=stake,
                        won=won,
                        profit=profit,
                        bankroll_after=bankroll,
                    )
                )

        return bankroll, records
