"""Integracion de TrialFlowService con TrialService y TrialSettlementService reales."""

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Bet, Event, Opportunity, Settlement
from app.risk.bankroll import FractionalKellyRiskManager, RiskConfig
from app.settlements.trial_settlement_service import TrialSettlementService
from app.trials.trial_flow_service import TrialFlowService
from app.trials.trial_service import TrialService

T1 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
T2 = T1 + timedelta(days=1)
START = datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc)


@pytest.fixture()
def flow(db_session):
    risk = FractionalKellyRiskManager(RiskConfig(kelly_fraction=0.25, max_stake_pct_per_bet=0.05))
    return TrialFlowService(TrialSettlementService(db_session), TrialService(db_session, risk))


def _event(db, n, start=START):
    e = Event(
        external_id=f"EV{n}", sport="soccer", league="L", competitor_home="A", competitor_away="B",
        start_time=start, status="scheduled", source="sample",
    )
    db.add(e)
    db.flush()
    return e


def _opportunity(db, event):
    o = Opportunity(
        event_id=event.id, market_type="1x2", selection="home", bookmaker="B", odds_value=2.0,
        estimated_probability=0.6, implied_probability=0.5, edge=0.1, expected_value=0.2,
        kelly_fraction_suggested=0.2, suggested_stake=10.0, status="candidate", created_at=T1,
    )
    db.add(o)
    db.flush()
    return o


def test_settlement_then_execution_across_two_runs(db_session, flow):
    first_event = _event(db_session, 1)
    _opportunity(db_session, first_event)
    db_session.commit()

    r1 = flow.run(now=T1, bankroll=1000.0)
    assert r1.settlement.processed == 0
    assert r1.execution.status == "executed"
    old_bet = r1.execution.bet
    assert old_bet.status == "pending"

    # El evento termina y aparece una nueva Opportunity para un evento futuro.
    first_event.status, first_event.result = "finished", "home_win"
    new_event = _event(db_session, 2, start=T2 + timedelta(hours=6))
    new_opp = _opportunity(db_session, new_event)
    db_session.commit()

    r2 = flow.run(now=T2, bankroll=1000.0)

    # Settlement primero: la Bet anterior quedo liquidada.
    assert r2.settlement.settled == [old_bet.id]
    settlement = db_session.query(Settlement).filter_by(bet_id=old_bet.id).one()
    assert settlement.status == "won" and settlement.settled_at.replace(tzinfo=timezone.utc) == T2
    assert old_bet.status == "settled"

    # Execution despues: evalua y ejecuta la nueva Opportunity.
    assert r2.execution.status == "executed"
    assert r2.execution.eligible_opportunity_ids == [new_opp.id]
    assert r2.execution.bet.id != old_bet.id and r2.execution.bet.status == "pending"
    assert db_session.query(Bet).count() == 2


def test_repeated_runs_do_not_duplicate(db_session, flow):
    _opportunity(db_session, _event(db_session, 1))
    db_session.commit()

    first = flow.run(now=T1, bankroll=1000.0)
    bet_id = first.execution.bet.id
    r = flow.run(now=T1, bankroll=1000.0)  # evento con Bet abierta -> excluido

    assert r.execution.status == "no_bet"
    assert r.settlement.settled == [] and r.settlement.unresolved == [bet_id]
    assert db_session.query(Bet).count() == 1
    assert db_session.query(Settlement).count() == 0
