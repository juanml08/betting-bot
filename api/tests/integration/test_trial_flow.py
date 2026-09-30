"""Integracion de TrialService.run_cycle con las piezas reales:
Opportunity -> DecisionEngine -> RecommendationService -> TrialExecutor -> Bet(pending).

Las Opportunity se crean con p/cuota controladas para saber que elegira el
engine. Settlement queda fuera de esta fase.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import OperationalError

from app.db.models import (
    BankrollTransaction,
    Bet,
    BetLeg,
    Event,
    Opportunity,
    Recommendation,
    RecommendationOpportunity,
    Settlement,
)
from app.db.repositories.bet_repository import BetRepository
from app.filters.opportunity_filters import OpportunityFilterConfig, ThresholdOpportunityFilter
from app.ingestion.providers.sample_data_provider import SampleDataProvider
from app.models.generic_rating_model import GenericRatingModel
from app.odds.providers.sample_odds_provider import SampleOddsProvider
from app.opportunities.opportunity_lifecycle_service import OpportunityLifecycleService
from app.opportunities.opportunity_service import OpportunityService
from app.risk.bankroll import FractionalKellyRiskManager, RiskConfig
from app.trials.trial_service import TrialService

PLACED_AT = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
START = datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc)
BANKROLL = 1000.0


@pytest.fixture()
def service(db_session) -> TrialService:
    risk = FractionalKellyRiskManager(RiskConfig(kelly_fraction=0.25, max_stake_pct_per_bet=0.05))
    return TrialService(db_session, risk)


def _event(db_session, n=1, *, status="scheduled", start_time=START) -> Event:
    event = Event(
        external_id=f"EV{n}-{status}",
        sport="soccer",
        league="L",
        competitor_home="A",
        competitor_away="B",
        start_time=start_time,
        status=status,
        source="sample",
    )
    db_session.add(event)
    db_session.flush()
    return event


def _opportunity(db_session, event, *, p=0.6, odds=2.0, kelly=0.2, status="candidate", selection="home"):
    o = Opportunity(
        event_id=event.id,
        market_type="1x2",
        selection=selection,
        bookmaker="SampleBook",
        odds_value=odds,
        estimated_probability=p,
        implied_probability=1 / odds,
        edge=p - 1 / odds,
        expected_value=p * odds - 1,
        kelly_fraction_suggested=kelly,
        suggested_stake=10.0,
        status=status,
        created_at=PLACED_AT,
    )
    db_session.add(o)
    db_session.flush()
    return o


def _counts(db_session) -> dict[str, int]:
    return {
        "recommendations": db_session.query(Recommendation).count(),
        "rec_opportunities": db_session.query(RecommendationOpportunity).count(),
        "bets": db_session.query(Bet).count(),
        "bet_legs": db_session.query(BetLeg).count(),
        "settlements": db_session.query(Settlement).count(),
        "bankroll_tx": db_session.query(BankrollTransaction).count(),
    }


# --- Test A / B: simple -----------------------------------------------------


def test_simple_cycle_creates_recommendation_and_pending_bet(db_session, service):
    opp = _opportunity(db_session, _event(db_session), p=0.6, odds=2.0, kelly=0.2)
    db_session.commit()

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert result.status == "executed" and result.reason is None
    rec, bet = result.recommendation, result.bet
    assert rec.bet_type == "simple" and rec.mode == "trial"
    assert [leg.opportunity_id for leg in rec.legs] == [opp.id]
    assert bet.status == "pending" and bet.mode == "trial" and bet.bet_type == "simple"
    assert bet.recommendation_id == rec.id
    assert float(bet.stake) == 50.0  # min(0.2 * 0.25, 5%) * 1000
    assert [float(leg.odds_taken) for leg in bet.legs] == [2.0]
    assert [leg.result for leg in bet.legs] == ["pending"]
    assert _counts(db_session)["settlements"] == 0


def test_only_positive_ev_opportunity_is_selected_among_several(db_session, service):
    """Escenario de una apuesta que puede perder: el ciclo solo llega al Bet
    (pending); la liquidacion pertenece a 5.7."""
    winner = _opportunity(db_session, _event(db_session, 1), p=0.55, odds=2.1, kelly=0.1)
    _opportunity(db_session, _event(db_session, 2), p=0.4, odds=2.0, kelly=0.0)  # EV < 0
    db_session.commit()

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert result.recommendation.bet_type == "simple"
    assert [leg.opportunity_id for leg in result.recommendation.legs] == [winner.id]
    assert len(result.bet.legs) == 1 and result.bet.status == "pending"
    assert _counts(db_session)["bets"] == 1


# --- Test C / D: compound ---------------------------------------------------


def test_compound_cycle_persists_all_legs_and_metadata(db_session, service):
    opps = [_opportunity(db_session, _event(db_session, n)) for n in (1, 2)]
    db_session.commit()

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    rec, bet = result.recommendation, result.bet
    assert rec.bet_type == "compound" and bet.bet_type == "compound"
    assert [leg.opportunity_id for leg in rec.legs] == [o.id for o in opps]
    assert [leg.event_id for leg in bet.legs] == [o.event_id for o in opps]
    assert float(bet.stake) > 0 and bet.status == "pending"
    assert rec.decision_metadata["selected"] == "compound"
    assert rec.decision_metadata["compound"]["opportunity_ids"] == [o.id for o in opps]
    assert rec.explanation
    assert _counts(db_session)["bet_legs"] == 2


def test_compound_cycle_with_three_events_persists_every_leg(db_session, service):
    opps = [_opportunity(db_session, _event(db_session, n), p=0.7, odds=2.0, kelly=0.4) for n in (1, 2, 3)]
    db_session.commit()

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    rec, bet = result.recommendation, result.bet
    assert rec.bet_type == bet.bet_type == "compound"
    assert [leg.opportunity_id for leg in rec.legs] == [o.id for o in opps]
    assert [leg.event_id for leg in bet.legs] == [o.event_id for o in opps]
    assert rec.decision_metadata["compound"]["number_of_legs"] == 3


# --- Test E: no_bet ----------------------------------------------------------


def test_no_bet_is_persisted_without_bet(db_session, service):
    _opportunity(db_session, _event(db_session), p=0.3, odds=2.0, kelly=0.0)  # EV < 0
    db_session.commit()

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert result.status == "no_bet" and result.reason == "no_bet" and result.bet is None
    assert result.recommendation.bet_type == "no_bet"
    assert _counts(db_session) == {
        "recommendations": 1,
        "rec_opportunities": 0,
        "bets": 0,
        "bet_legs": 0,
        "settlements": 0,
        "bankroll_tx": 0,
    }


def test_cycle_without_eligible_opportunities_persists_no_bet(db_session, service):
    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert result.status == "no_bet" and result.eligible_opportunity_ids == []
    assert result.recommendation.decision_metadata["counts"]["candidate"] == 0
    assert _counts(db_session)["recommendations"] == 1 and _counts(db_session)["bets"] == 0


# --- Test F: repeticion -----------------------------------------------------


def test_second_cycle_does_not_execute_again_for_same_event(db_session, service):
    _opportunity(db_session, _event(db_session), p=0.6, odds=2.0, kelly=0.2)
    db_session.commit()

    first = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)
    second = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert first.status == "executed"
    assert second.status == "no_bet" and second.bet is None
    assert second.eligible_opportunity_ids == []  # el pre-filtro dejo el evento fuera
    counts = _counts(db_session)
    assert counts["bets"] == 1 and counts["bet_legs"] == 1
    # La segunda corrida solo deja una Recommendation no ejecutable (no_bet).
    assert counts["recommendations"] == 2 and counts["rec_opportunities"] == 1


def test_fresh_duplicate_opportunity_for_same_event_is_not_executed(db_session, service):
    """Una Opportunity nueva (otro slot) para un evento ya apostado no debe
    producir un segundo Bet."""
    event = _event(db_session)
    _opportunity(db_session, event)
    db_session.commit()
    service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    _opportunity(db_session, event, selection="draw")  # otra seleccion del mismo evento
    db_session.commit()
    second = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert second.status == "no_bet"
    assert _counts(db_session)["bets"] == 1


# --- Test H: rollback -------------------------------------------------------


def test_executor_failure_rolls_back_recommendation_and_bet(db_session, service, monkeypatch):
    _opportunity(db_session, _event(db_session))
    db_session.commit()

    def boom(self, **kwargs):
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr(BetRepository, "create", boom)

    with pytest.raises(OperationalError):
        service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    counts = _counts(db_session)
    assert counts["recommendations"] == 0 and counts["rec_opportunities"] == 0
    assert counts["bets"] == 0 and counts["bet_legs"] == 0
    assert db_session.query(Opportunity).count() == 1  # lo previamente commiteado sigue


def test_business_error_from_executor_propagates_and_rolls_back(db_session, service):
    # kelly 0 con EV>0: el engine lo elige pero RiskManager devuelve stake 0.
    _opportunity(db_session, _event(db_session), p=0.6, odds=2.0, kelly=0.0)
    db_session.commit()

    from app.trials.trial_executor import RecommendationNotExecutableError

    with pytest.raises(RecommendationNotExecutableError):
        service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert _counts(db_session)["recommendations"] == 0
    assert _counts(db_session)["bets"] == 0


# --- Pre-filtro -------------------------------------------------------------


@pytest.mark.parametrize("status", ["live", "finished", "cancelled"])
def test_event_with_non_scheduled_status_is_excluded(db_session, service, status):
    _opportunity(db_session, _event(db_session, status=status))
    db_session.commit()

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert result.status == "no_bet" and result.eligible_opportunity_ids == []


@pytest.mark.parametrize("delta_seconds", [0, 60])
def test_event_already_started_is_excluded(db_session, service, delta_seconds):
    _opportunity(db_session, _event(db_session, start_time=PLACED_AT - timedelta(seconds=delta_seconds)))
    db_session.commit()

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert result.status == "no_bet" and result.eligible_opportunity_ids == []


def test_non_candidate_opportunity_does_not_reach_engine(db_session, service):
    _opportunity(db_session, _event(db_session), status="expired")
    db_session.commit()

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert result.eligible_opportunity_ids == []
    assert result.recommendation.decision_metadata["counts"]["candidate"] == 0


def test_event_with_open_trial_bet_is_excluded_but_other_events_are_not(db_session, service):
    busy, free = _event(db_session, 1), _event(db_session, 2)
    _opportunity(db_session, busy, p=0.9, odds=3.0, kelly=0.4)  # la mejor, pero evento ocupado
    free_opp = _opportunity(db_session, free, p=0.55, odds=2.0, kelly=0.1)
    BetRepository(db_session).create(
        bet_type="simple", mode="trial", stake=10.0, bankroll_at_time=BANKROLL, placed_at=PLACED_AT,
        legs=[dict(event_id=busy.id, market_type="1x2", selection="home", bookmaker="B", odds_taken=3.0)],
    )
    db_session.commit()

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert result.eligible_opportunity_ids == [free_opp.id]
    assert [leg.opportunity_id for leg in result.recommendation.legs] == [free_opp.id]
    assert _counts(db_session)["bets"] == 2


def test_settled_trial_bet_or_real_bet_does_not_block_event(db_session, service):
    event = _event(db_session)
    opp = _opportunity(db_session, event)
    leg = [dict(event_id=event.id, market_type="1x2", selection="home", bookmaker="B", odds_taken=2.0)]
    settled = BetRepository(db_session).create(
        bet_type="simple", mode="trial", stake=10.0, bankroll_at_time=BANKROLL, placed_at=PLACED_AT, legs=leg
    )
    settled.status = "settled"
    BetRepository(db_session).create(
        bet_type="simple", mode="real", stake=10.0, bankroll_at_time=BANKROLL, placed_at=PLACED_AT, legs=leg
    )
    db_session.commit()

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert result.eligible_opportunity_ids == [opp.id]
    assert result.status == "executed"


def test_multiple_eligible_events_in_one_cycle(db_session, service):
    opps = [_opportunity(db_session, _event(db_session, n), p=0.5 + n / 20, odds=2.2) for n in (1, 2, 3)]
    db_session.commit()

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert result.eligible_opportunity_ids == [o.id for o in opps]
    assert result.status == "executed"
    assert result.recommendation.decision_metadata["counts"]["candidate"] == 3


# --- Bankroll / metadata ------------------------------------------------------


def test_explicit_bankroll_is_persisted_and_drives_stake(db_session, service):
    _opportunity(db_session, _event(db_session), p=0.6, odds=2.0, kelly=0.2)
    db_session.commit()

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=400.0)

    assert float(result.recommendation.bankroll_at_recommendation) == 400.0
    assert float(result.bet.bankroll_at_time) == 400.0
    assert float(result.bet.stake) == 20.0  # 5% de 400
    assert _counts(db_session)["bankroll_tx"] == 0


def test_recommendation_preserves_decision_result(db_session, service):
    _opportunity(db_session, _event(db_session))
    db_session.commit()

    rec = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL).recommendation

    assert rec.mode == "trial"
    assert rec.explanation and rec.decision_metadata["selected"] == "simple"
    assert rec.generated_at.replace(tzinfo=None) == PLACED_AT.replace(tzinfo=None)
    assert rec.strategy_name == "decision_engine"


# --- Fase 5.12: la elegibilidad estructural vive en el repository ------------


def test_trial_service_delegates_eligibility_to_repository(db_session, service, monkeypatch):
    from app.db.repositories.opportunity_repository import OpportunityRepository

    calls = []

    def fake(self, *, now, ttl):
        calls.append((now, ttl))
        return []

    monkeypatch.setattr(OpportunityRepository, "list_eligible", fake)
    _opportunity(db_session, _event(db_session))  # candidate valida, pero el repository manda
    db_session.commit()

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert result.status == "no_bet" and result.eligible_opportunity_ids == []
    assert calls == [(PLACED_AT, timedelta(seconds=180))]  # TTL por defecto: 3 x 60 s


def test_trial_service_only_adds_the_pending_trial_bet_rule(db_session, service, monkeypatch):
    from app.db.repositories.opportunity_repository import OpportunityRepository

    busy = _opportunity(db_session, _event(db_session, 1))
    db_session.commit()
    service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)  # abre un Bet sobre el evento 1
    free = _opportunity(db_session, _event(db_session, 2))
    db_session.commit()
    monkeypatch.setattr(OpportunityRepository, "list_eligible", lambda self, **kw: [busy, free])

    result = service.run_cycle(placed_at=PLACED_AT, bankroll=BANKROLL)

    assert result.eligible_opportunity_ids == [free.id]


def test_custom_ttl_controls_eligibility(db_session):
    risk = FractionalKellyRiskManager(RiskConfig(kelly_fraction=0.25, max_stake_pct_per_bet=0.05))
    _opportunity(db_session, _event(db_session))  # last_observed_at = PLACED_AT
    db_session.commit()
    later = PLACED_AT + timedelta(minutes=10)

    short = TrialService(db_session, risk, opportunity_ttl=timedelta(minutes=5)).run_cycle(
        placed_at=later, bankroll=BANKROLL
    )
    assert short.eligible_opportunity_ids == []

    long = TrialService(db_session, risk, opportunity_ttl=timedelta(minutes=15)).run_cycle(
        placed_at=later, bankroll=BANKROLL
    )
    assert len(long.eligible_opportunity_ids) == 1


# --- Humo con OpportunityService real ---------------------------------------


def test_smoke_with_real_opportunity_service(db_session, seeded_events, service):
    opportunity_service = OpportunityService(
        data_provider=SampleDataProvider(),
        odds_provider=SampleOddsProvider(),
        probability_model=GenericRatingModel(),
        opportunity_filter=ThresholdOpportunityFilter(
            OpportunityFilterConfig(min_edge=-1.0, min_expected_value=-1.0, min_odds=1.0, max_odds=100.0)
        ),
        risk_manager=FractionalKellyRiskManager(RiskConfig(kelly_fraction=0.25, max_stake_pct_per_bet=0.05)),
    )
    observation = opportunity_service.generate_observation(current_bankroll=BANKROLL)
    OpportunityLifecycleService(db_session).apply(observation)

    # No se asume que apuesta elige el engine con datos de muestra.
    result = service.run_cycle(placed_at=datetime(2025, 1, 1, tzinfo=timezone.utc), bankroll=BANKROLL)

    assert result.status in ("executed", "no_bet")
    assert (result.bet is not None) == (result.status == "executed")
    if result.bet is not None:
        assert result.bet.status == "pending" and result.bet.recommendation_id == result.recommendation.id
