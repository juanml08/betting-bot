"""Fase 5.10 - Tests de caracterizacion del Trial automatico.

NO validan el comportamiento deseado: dejan explicitamente protegido lo que el
sistema hace HOY (incluidas limitaciones conocidas), para que un cambio futuro
sea una decision consciente y no un efecto colateral. Cada test enlaza con un
hallazgo del informe de auditoria (F-xx).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    BankrollTransaction,
    Bet,
    Event,
    Opportunity,
    Recommendation,
    RecommendationOpportunity,
    Settlement,
)
from app.db.repositories.bet_repository import BetRepository
from app.risk.bankroll import FractionalKellyRiskManager, RiskConfig
from app.settlements.trial_settlement_service import TrialSettlementService
from app.trials.trial_flow_service import TrialFlowService
from app.trials.trial_service import TrialService

T0 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
START = datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc)


def _risk():
    return FractionalKellyRiskManager(RiskConfig(kelly_fraction=0.25, max_stake_pct_per_bet=0.05))


@pytest.fixture()
def flow(db_session):
    return TrialFlowService(TrialSettlementService(db_session), TrialService(db_session, _risk()))


def _event(db, n, *, status="scheduled", result=None, start=START):
    e = Event(
        external_id=f"AUD{n}", sport="soccer", league="L", competitor_home="A", competitor_away="B",
        start_time=start, status=status, source="sample", result=result,
    )
    db.add(e)
    db.flush()
    return e


def _opp(db, event, *, p=0.6, odds=2.0, kelly=0.2, selection="home", created_at=T0, version=1):
    o = Opportunity(
        event_id=event.id, market_type="1x2", selection=selection, bookmaker="B", odds_value=odds,
        estimated_probability=p, implied_probability=1 / odds, edge=p - 1 / odds,
        expected_value=p * odds - 1, kelly_fraction_suggested=kelly, suggested_stake=10.0,
        status="candidate", created_at=created_at, version=version,
    )
    db.add(o)
    db.flush()
    return o


def _leg(event, selection="home", odds=2.0):
    return dict(event_id=event.id, market_type="1x2", selection=selection, bookmaker="B", odds_taken=odds)


# F-01 / F-02: el bankroll es un parametro constante; ni el stake ni el P/L lo modifican.
def test_bankroll_is_constant_so_open_exposure_can_exceed_it(db_session):
    bankroll = 500.0
    risk = FractionalKellyRiskManager(RiskConfig(kelly_fraction=1.0, max_stake_pct_per_bet=0.20))
    flow = TrialFlowService(TrialSettlementService(db_session), TrialService(db_session, risk))
    for n in range(1, 31):
        _opp(db_session, _event(db_session, n), p=0.9, odds=3.0, kelly=0.85)  # cada Bet consume hasta 3 eventos
    db_session.commit()

    # 1 Bet por ciclo hasta agotar los eventos libres.
    while flow.run(now=T0, bankroll=bankroll).execution.status == "executed":
        pass

    bets = db_session.query(Bet).all()
    assert {float(b.bankroll_at_time) for b in bets} == {bankroll}  # nunca baja
    assert {float(b.stake) for b in bets} == {100.0}  # tope configurado 20% de 500, siempre sobre el mismo bankroll
    assert sum(float(b.stake) for b in bets) > bankroll  # exposicion abierta > bankroll
    assert db_session.query(BankrollTransaction).count() == 0  # no hay ledger


# F-03: 'no_bet' se persiste en cada ciclo, sin limite ni deduplicacion.
def test_every_idle_cycle_persists_a_no_bet_recommendation(db_session, flow):
    for _ in range(10):
        assert flow.run(now=T0, bankroll=500.0).execution.status == "no_bet"

    assert db_session.query(Recommendation).filter_by(bet_type="no_bet").count() == 10
    assert db_session.query(RecommendationOpportunity).count() == 0
    assert db_session.query(Bet).count() == 0


# F-04: Opportunity nunca cambia de estado; queda 'candidate' aunque se apueste y se liquide.
def test_opportunity_stays_candidate_after_bet_and_settlement(db_session, flow):
    event = _event(db_session, 1)
    opp = _opp(db_session, event)
    db_session.commit()

    flow.run(now=T0, bankroll=1000.0)
    event.status, event.result = "finished", "home_win"
    db_session.commit()
    flow.run(now=T0 + timedelta(days=1), bankroll=1000.0)

    assert db_session.query(Settlement).one().status == "won"
    assert db_session.get(Opportunity, opp.id).status == "candidate"


# F-05 (corregido en 5.12): una version vieja supersedida ya no compite; solo la
# version vigente llega al engine y su cuota es la que queda congelada.
def test_superseded_stale_opportunity_cannot_compete_with_current_version(db_session, flow):
    event = _event(db_session, 1)
    stale = _opp(db_session, event, p=0.6, odds=2.5, created_at=T0 - timedelta(minutes=1))
    current = _opp(db_session, event, p=0.6, odds=2.0, created_at=T0, version=2)
    stale.status, stale.superseded_by_id, stale.superseded_at = "superseded", current.id, T0
    db_session.commit()

    result = flow.run(now=T0, bankroll=1000.0).execution

    assert result.eligible_opportunity_ids == [current.id]
    assert [leg.opportunity_id for leg in result.recommendation.legs] == [current.id]
    assert float(result.bet.legs[0].odds_taken) == 2.0


# F-05 (TTL): una candidata sin reconfirmar mas alla del TTL deja de ser elegible.
def test_candidate_older_than_ttl_is_not_eligible(db_session, flow):
    event = _event(db_session, 1)
    _opp(db_session, event, created_at=T0 - timedelta(days=3))
    db_session.commit()

    result = flow.run(now=T0, bankroll=1000.0).execution

    assert result.status == "no_bet" and result.eligible_opportunity_ids == []


# F-06: won + void -> manual_review deja la Bet 'pending', fuera de settle_due y sin salida por API.
def test_manual_review_bet_stays_pending_and_is_never_reprocessed(db_session, flow):
    finished = _event(db_session, 1, status="finished", result="home_win")
    cancelled = _event(db_session, 2, status="cancelled")
    bet = BetRepository(db_session).create(
        bet_type="compound", mode="trial", stake=10.0, bankroll_at_time=1000.0, placed_at=T0,
        legs=[_leg(finished), _leg(cancelled)],
    )
    db_session.commit()

    first = flow.run(now=T0, bankroll=1000.0)
    second = flow.run(now=T0 + timedelta(days=30), bankroll=1000.0)

    settlement = db_session.query(Settlement).filter_by(bet_id=bet.id).one()
    assert settlement.status == "manual_review" and settlement.payout is None
    assert db_session.get(Bet, bet.id).status == "pending"
    assert first.settlement.settled == [bet.id]  # se reporta como 'settled' aunque siga pending
    assert second.settlement.processed == 0  # settle_due ya no la considera


# F-07: una combinada con una leg ya perdida espera a que terminen las demas.
def test_compound_with_lost_leg_waits_for_pending_leg(db_session, flow):
    lost = _event(db_session, 1, status="finished", result="away_win")
    open_ = _event(db_session, 2, status="scheduled", start=T0 + timedelta(days=60))
    bet = BetRepository(db_session).create(
        bet_type="compound", mode="trial", stake=10.0, bankroll_at_time=1000.0, placed_at=T0,
        legs=[_leg(lost), _leg(open_)],
    )
    db_session.commit()

    result = flow.run(now=T0, bankroll=1000.0)

    assert result.settlement.unresolved == [bet.id]
    assert db_session.query(Settlement).count() == 0


# F-08: la ventana check-then-act. Dos runners con el mismo pre-filtro duplican el Bet en el evento;
# Bet.recommendation_id UNIQUE no protege porque cada runner crea su PROPIA Recommendation.
def test_two_runners_with_stale_prefilter_double_bet_the_same_event(db_engine, db_session):
    event = _event(db_session, 1)
    _opp(db_session, event)
    db_session.commit()

    session_b = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)()
    try:
        runner_a = TrialService(db_session, _risk())
        runner_b = TrialService(session_b, _risk())

        stale_eligible = runner_a._eligible_opportunities(T0)  # A ve el evento libre
        assert [o.event_id for o in stale_eligible] == [event.id]
        assert runner_b.run_cycle(placed_at=T0, bankroll=1000.0).status == "executed"  # B apuesta primero

        runner_a._eligible_opportunities = lambda _placed_at: stale_eligible  # A ya habia filtrado
        assert runner_a.run_cycle(placed_at=T0, bankroll=1000.0).status == "executed"
    finally:
        session_b.close()

    db_session.expire_all()
    pending = db_session.query(Bet).filter_by(mode="trial", status="pending").all()
    assert len(pending) == 2
    assert {leg.event_id for b in pending for leg in b.legs} == {event.id}
    assert len({b.recommendation_id for b in pending}) == 2


# F-09: sin nadie que actualice Event.status/result, nada avanza aunque el reloj pase.
def test_pending_bet_never_settles_while_event_status_is_not_updated(db_session, flow):
    _opp(db_session, _event(db_session, 1))
    db_session.commit()
    bet_id = flow.run(now=T0, bankroll=1000.0).execution.bet.id

    later = flow.run(now=T0 + timedelta(days=365), bankroll=1000.0)  # el evento 'scheduled' sigue igual

    assert later.settlement.unresolved == [bet_id]
    assert db_session.query(Settlement).count() == 0
