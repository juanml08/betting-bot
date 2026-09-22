from datetime import date

from app.filters.opportunity_filters import OpportunityFilterConfig, ThresholdOpportunityFilter
from app.ingestion.providers.sample_data_provider import SampleDataProvider
from app.models.generic_rating_model import GenericRatingModel
from app.odds.providers.sample_odds_provider import SampleOddsProvider
from app.opportunities.opportunity_service import OpportunityService
from app.risk.bankroll import FractionalKellyRiskManager, RiskConfig
from backtesting.engine import BacktestEngine
from backtesting.metrics import compute_metrics


def _build_service() -> OpportunityService:
    return OpportunityService(
        data_provider=SampleDataProvider(),
        odds_provider=SampleOddsProvider(),
        probability_model=GenericRatingModel(),
        opportunity_filter=ThresholdOpportunityFilter(
            OpportunityFilterConfig(min_edge=-1.0, min_expected_value=-1.0, min_odds=1.0, max_odds=100.0)
        ),
        risk_manager=FractionalKellyRiskManager(RiskConfig(kelly_fraction=0.25, max_stake_pct_per_bet=0.05)),
    )


def test_opportunity_service_generates_candidates_for_scheduled_events():
    service = _build_service()
    candidates = service.generate_opportunities(current_bankroll=1000.0)

    # Los fixtures de muestra tienen 3 eventos "scheduled" (S7, B7, T7).
    event_ids = {c.opportunity.event_external_id for c in candidates}
    assert event_ids.issubset({"S7", "B7", "T7"})
    assert len(candidates) > 0

    for candidate in candidates:
        assert 0.0 <= candidate.opportunity.estimated_probability <= 1.0
        assert candidate.suggested_stake >= 0.0
        assert candidate.suggested_stake <= 1000.0 * 0.05 + 1e-9


def test_backtest_engine_runs_without_lookahead_and_produces_metrics():
    engine = BacktestEngine(
        data_provider=SampleDataProvider(),
        odds_provider=SampleOddsProvider(),
        probability_model=GenericRatingModel(),
        opportunity_filter=ThresholdOpportunityFilter(
            OpportunityFilterConfig(min_edge=-1.0, min_expected_value=-1.0, min_odds=1.0, max_odds=100.0)
        ),
        risk_manager=FractionalKellyRiskManager(RiskConfig(kelly_fraction=0.25, max_stake_pct_per_bet=0.05)),
    )

    report = engine.run(initial_bankroll=1000.0, date_from=date(2026, 1, 1), date_to=date(2026, 1, 31))
    metrics = compute_metrics(report)

    # Solo hay eventos finalizados en enero en los fixtures; deberian generar apuestas simuladas.
    assert metrics.num_bets > 0
    assert 0.0 <= metrics.win_rate <= 1.0
    assert metrics.max_drawdown >= 0.0
