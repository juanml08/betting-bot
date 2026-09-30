"""Integracion de TrialSettlementService.settle_due con SettlementService real."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import Event, Settlement
from app.db.repositories.bet_repository import BetRepository
from app.db.repositories.settlement_repository import SettlementRepository
from app.settlements.trial_settlement_service import TrialSettlementService

PLACED = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
SETTLED = datetime(2026, 1, 6, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def service(db_session):
    return TrialSettlementService(db_session)


def _event(db, n, status="finished", result="home_win"):
    e = Event(
        external_id=f"EV{n}", sport="soccer", league="L", competitor_home="A", competitor_away="B",
        start_time=PLACED, status=status, source="sample", result=result,
    )
    db.add(e)
    db.flush()
    return e


def _bet(db, events, selections=None, *, mode="trial", odds=2.0, stake=10.0):
    selections = selections or ["home"] * len(events)
    legs = [
        dict(event_id=e.id, market_type="1x2", selection=s, bookmaker="B", odds_taken=odds)
        for e, s in zip(events, selections)
    ]
    bet = BetRepository(db).create(
        bet_type="simple" if len(legs) == 1 else "compound",
        mode=mode, stake=stake, bankroll_at_time=1000.0, placed_at=PLACED, legs=legs,
    )
    db.commit()
    return bet


def _settlement(db, bet):
    return db.scalars(select(Settlement).where(Settlement.bet_id == bet.id)).one_or_none()


def _leg_results(bet):
    return [leg.result for leg in sorted(bet.legs, key=lambda x: x.leg_order)]


def test_simple_win(db_session, service):
    bet = _bet(db_session, [_event(db_session, 1)])
    r = service.settle_due(settled_at=SETTLED)
    assert r.processed == 1 and r.settled == [bet.id]
    s = _settlement(db_session, bet)
    assert s.status == "won" and float(s.payout) == 20.0
    assert bet.status == "settled" and _leg_results(bet) == ["won"]


def test_simple_loss(db_session, service):
    bet = _bet(db_session, [_event(db_session, 1, result="away_win")])
    service.settle_due(settled_at=SETTLED)
    assert _settlement(db_session, bet).status == "lost"
    assert bet.status == "settled" and _leg_results(bet) == ["lost"]


@pytest.mark.parametrize("result", [None, "home_win"])
def test_simple_void_cancelled(db_session, service, result):
    bet = _bet(db_session, [_event(db_session, 1, status="cancelled", result=result)])
    service.settle_due(settled_at=SETTLED)
    s = _settlement(db_session, bet)
    assert s.status == "void" and float(s.payout) == 10.0
    assert bet.status == "settled" and _leg_results(bet) == ["void"]


def test_compound_win(db_session, service):
    bet = _bet(db_session, [_event(db_session, i) for i in range(3)])
    service.settle_due(settled_at=SETTLED)
    assert _settlement(db_session, bet).status == "won"
    assert _leg_results(bet) == ["won"] * 3


def test_compound_loss(db_session, service):
    events = [_event(db_session, 1), _event(db_session, 2, result="away_win"), _event(db_session, 3)]
    bet = _bet(db_session, events)
    service.settle_due(settled_at=SETTLED)
    assert _settlement(db_session, bet).status == "lost"
    assert _leg_results(bet) == ["won", "lost", "won"]


@pytest.mark.parametrize("status,result", [("live", "home_win"), ("scheduled", None), ("finished", None)])
def test_compound_incomplete_stays_pending(db_session, service, status, result):
    bet = _bet(db_session, [_event(db_session, 1), _event(db_session, 2, status, result)])
    r = service.settle_due(settled_at=SETTLED)
    assert r.unresolved == [bet.id] and r.settled == [] and r.failed == []
    assert _settlement(db_session, bet) is None
    assert bet.status == "pending" and _leg_results(bet) == ["pending", "pending"]


def test_won_plus_void_is_manual_review(db_session, service):
    bet = _bet(db_session, [_event(db_session, 1), _event(db_session, 2, status="cancelled", result=None)])
    r = service.settle_due(settled_at=SETTLED)
    assert r.settled == [bet.id]
    s = _settlement(db_session, bet)
    assert s.status == "manual_review" and s.payout is None
    assert bet.status == "pending"
    # No se reintenta: ya tiene Settlement.
    assert service.settle_due(settled_at=SETTLED).processed == 0


def test_all_void(db_session, service):
    events = [_event(db_session, i, status="cancelled", result=None) for i in range(2)]
    bet = _bet(db_session, events)
    service.settle_due(settled_at=SETTLED)
    assert _settlement(db_session, bet).status == "void"
    assert bet.status == "settled"


def test_finished_without_result_stays_pending(db_session, service):
    bet = _bet(db_session, [_event(db_session, 1, result=None)])
    service.settle_due(settled_at=SETTLED)
    assert db_session.scalar(select(func.count(Settlement.id))) == 0
    assert bet.status == "pending" and _leg_results(bet) == ["pending"]


def test_only_pending_trial_bets(db_session, service):
    real = _bet(db_session, [_event(db_session, 1)], mode="real")
    trial = _bet(db_session, [_event(db_session, 2)])
    r = service.settle_due(settled_at=SETTLED)
    assert r.processed == 1 and r.settled == [trial.id]
    assert _settlement(db_session, real) is None and real.status == "pending"
    assert service.settle_due(settled_at=SETTLED).processed == 0  # settled ya no se toca


def test_idempotent(db_session, service):
    bet = _bet(db_session, [_event(db_session, 1)])
    service.settle_due(settled_at=SETTLED)
    first = _settlement(db_session, bet)
    snapshot = (first.id, first.status, float(first.payout), first.settled_at)
    r = service.settle_due(settled_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
    assert r.processed == 0
    assert db_session.scalar(select(func.count(Settlement.id))) == 1
    again = _settlement(db_session, bet)
    assert (again.id, again.status, float(again.payout), again.settled_at) == snapshot


def test_mixed_batch_isolated(db_session, service):
    ok = _bet(db_session, [_event(db_session, 1)])
    pending = _bet(db_session, [_event(db_session, 2, status="live")])
    lost = _bet(db_session, [_event(db_session, 3, result="draw")])
    r = service.settle_due(settled_at=SETTLED)
    assert r.processed == 3 and r.settled == [ok.id, lost.id] and r.unresolved == [pending.id]


def test_duplicate_settlement_race_is_already_settled(db_session, service, monkeypatch):
    """Otro proceso liquido entre el pre-check y el INSERT: UNIQUE(bet_id)."""
    bet = _bet(db_session, [_event(db_session, 1)])
    other = _bet(db_session, [_event(db_session, 2)])
    db_session.add(Settlement(bet_id=bet.id, settled_at=SETTLED, status="won", payout=20, profit_loss=10))
    db_session.commit()

    real_get = SettlementRepository.get_by_bet
    calls = {"n": 0}

    def blind_first(self, bet_id):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_get(self, bet_id)

    monkeypatch.setattr(SettlementRepository, "get_by_bet", blind_first)
    # Simula que la Bet ya liquidada aun figuraba como abierta al listar.
    monkeypatch.setattr(TrialSettlementService, "_open_bet_ids", lambda self: [bet.id, other.id])

    r = service.settle_due(settled_at=SETTLED)
    assert r.already_settled == [bet.id] and r.settled == [other.id] and r.failed == []
    assert db_session.scalar(select(func.count(Settlement.id))) == 2


def test_other_integrity_error_not_hidden(db_session, service, monkeypatch):
    bet = _bet(db_session, [_event(db_session, 1)])

    def boom(*args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("fk violation"))

    monkeypatch.setattr(SettlementRepository, "create", boom)
    r = service.settle_due(settled_at=SETTLED)
    assert r.already_settled == [] and r.settled == []
    assert [b for b, _ in r.failed] == [bet.id]
    assert _settlement(db_session, bet) is None and bet.status == "pending"
    assert _leg_results(bet) == ["pending"]


def test_technical_error_isolated_and_reported(db_session, service, monkeypatch):
    bad = _bet(db_session, [_event(db_session, 1)])
    good = _bet(db_session, [_event(db_session, 2)])
    real = service._settlement_service.settle_bet

    def flaky(bet_id, **kw):
        if bet_id == bad.id:
            raise RuntimeError("db down")
        return real(bet_id, **kw)

    monkeypatch.setattr(service._settlement_service, "settle_bet", flaky)
    r = service.settle_due(settled_at=SETTLED)
    assert r.settled == [good.id] and r.failed[0][0] == bad.id and "db down" in r.failed[0][1]
    assert _settlement(db_session, good).status == "won"
    assert _settlement(db_session, bad) is None and bad.status == "pending"
