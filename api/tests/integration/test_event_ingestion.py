"""Fase 5.11: EventIngestionService con Event/Bet reales y TrialSettlementService real."""

from datetime import datetime, timezone

import pytest

from app.db.models import Bet, Event, Settlement
from app.db.repositories.bet_repository import BetRepository
from app.domain.interfaces import EventUpdateProvider
from app.domain.models import EventUpdate
from app.ingestion.event_ingestion_service import EventIngestionService
from app.ingestion.providers.in_memory_event_update_provider import InMemoryEventUpdateProvider
from app.settlements.result_resolver import resolve_leg_result
from app.settlements.trial_settlement_service import TrialSettlementService

NOW = datetime(2026, 1, 6, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def service(db_session):
    return EventIngestionService(db_session)


def _event(db, n=1, status="scheduled", result=None) -> Event:
    e = Event(
        external_id=f"X{n}", sport="soccer", league="L", competitor_home="A", competitor_away="B",
        start_time=NOW, status=status, source="test", result=result,
    )
    db.add(e)
    db.commit()
    return e


def _state(db, event):
    db.expire_all()
    e = db.get(Event, event.id)
    return e.status, e.result


def test_provider_satisfies_protocol():
    provider: EventUpdateProvider = InMemoryEventUpdateProvider()
    assert provider.get_event_updates() == []


# --- A-E: transiciones validas ---------------------------------------------


@pytest.mark.parametrize(
    "start,new,result",
    [
        ("scheduled", "live", None),  # A
        ("live", "finished", "home_win"),  # B
        ("scheduled", "finished", "away_win"),  # C
        ("scheduled", "cancelled", None),  # D
        ("live", "cancelled", None),  # E
    ],
)
def test_valid_transitions(db_session, service, start, new, result):
    event = _event(db_session, status=start)

    r = service.ingest([EventUpdate("X1", new, result)])

    assert r.updated == ["X1"] and not r.rejected and not r.failed
    assert _state(db_session, event) == (new, result)


# --- F-H: resultados --------------------------------------------------------


@pytest.mark.parametrize("result", ["home_win", "away_win", "draw"])
def test_finished_results(db_session, service, result):
    event = _event(db_session, status="live")
    service.ingest([EventUpdate("X1", "finished", result)])
    assert _state(db_session, event) == ("finished", result)


# --- I: idempotencia --------------------------------------------------------


def test_repeated_update_is_idempotent(db_session, service):
    event = _event(db_session)
    update = EventUpdate("X1", "finished", "home_win")

    first = service.ingest([update])
    second = service.ingest([update])
    third = service.ingest([update])

    assert first.updated == ["X1"]
    assert second.unchanged == ["X1"] and third.unchanged == ["X1"]
    assert not second.updated and not second.rejected
    assert _state(db_session, event) == ("finished", "home_win")
    assert db_session.query(Event).count() == 1
    assert db_session.query(Settlement).count() == 0  # la ingesta nunca liquida


# --- J: evento desconocido --------------------------------------------------


def test_unknown_event_is_reported_and_not_created(db_session, service):
    r = service.ingest([EventUpdate("NOPE", "finished", "draw")])

    assert r.unknown == ["NOPE"] and r.processed == 1
    assert db_session.query(Event).count() == 0


# --- K: datos invalidos -----------------------------------------------------


@pytest.mark.parametrize(
    "status,result",
    [
        ("finished", "something_unknown"),
        ("finished", None),
        ("live", "home_win"),
        ("scheduled", "draw"),
        ("cancelled", "home_win"),
        ("postponed", None),
    ],
)
def test_invalid_data_is_rejected_and_state_kept(db_session, service, status, result):
    event = _event(db_session, status="live")

    r = service.ingest([EventUpdate("X1", status, result)])

    assert [ext for ext, _ in r.rejected] == ["X1"] and not r.updated
    assert _state(db_session, event) == ("live", None)


# --- L: transiciones invalidas ---------------------------------------------


@pytest.mark.parametrize(
    "start,start_result,new,new_result",
    [
        ("finished", "home_win", "live", None),
        ("finished", "home_win", "scheduled", None),
        ("finished", "home_win", "cancelled", None),
        ("cancelled", None, "live", None),
        ("cancelled", None, "finished", "home_win"),
        ("live", None, "scheduled", None),
        ("finished", "home_win", "finished", "away_win"),  # corregir resultado
    ],
)
def test_invalid_transitions_are_rejected(db_session, service, start, start_result, new, new_result):
    event = _event(db_session, status=start, result=start_result)

    r = service.ingest([EventUpdate("X1", new, new_result)])

    assert len(r.rejected) == 1 and not r.updated
    assert _state(db_session, event) == (start, start_result)


# --- Batch, aislamiento y resultado estructurado ----------------------------


def test_batch_reports_each_outcome(db_session, service):
    for n in (1, 2, 3):
        _event(db_session, n)
    r = service.ingest([
        EventUpdate("X1", "live"),
        EventUpdate("X2", "finished", "bogus"),
        EventUpdate("X3", "scheduled"),
        EventUpdate("X9", "live"),
    ])

    assert (r.processed, r.updated, r.unchanged, r.unknown) == (4, ["X1"], ["X3"], ["X9"])
    assert [e for e, _ in r.rejected] == ["X2"]


def test_technical_error_is_isolated_per_event(db_session, monkeypatch):
    first, second = _event(db_session, 1), _event(db_session, 2)
    service = EventIngestionService(db_session)
    real = service._events.apply_update

    def flaky(event, **kwargs):
        real(event, **kwargs)
        if event.external_id == "X1":
            raise RuntimeError("boom")

    monkeypatch.setattr(service._events, "apply_update", flaky)

    r = service.ingest([EventUpdate("X1", "live"), EventUpdate("X2", "live")])

    assert [e for e, _ in r.failed] == ["X1"] and r.updated == ["X2"]
    assert _state(db_session, first) == ("scheduled", None)  # rollback, sin cambios parciales
    assert _state(db_session, second) == ("live", None)


def test_sync_reads_from_provider(db_session, service):
    event = _event(db_session)
    provider = InMemoryEventUpdateProvider()
    provider.push("X1", "live")

    assert service.sync(provider).updated == ["X1"]
    assert _state(db_session, event) == ("live", None)


# --- M-O: integracion con Settlement ---------------------------------------


def _pending_bet(db, event, selection="home"):
    bet = BetRepository(db).create(
        bet_type="simple", mode="trial", stake=10.0, bankroll_at_time=1000.0, placed_at=NOW,
        legs=[dict(event_id=event.id, market_type="1x2", selection=selection, bookmaker="B", odds_taken=2.0)],
    )
    db.commit()
    return bet


@pytest.mark.parametrize(
    "selection,expected,payout",
    [("home", "won", 20.0), ("away", "lost", None)],
)
def test_finished_event_is_settled_by_next_settle_due(db_session, service, selection, expected, payout):
    """N + O + E2E: la ingesta solo cambia Event; settle_due liquida despues."""
    event = _event(db_session)
    bet = _pending_bet(db_session, event, selection)
    settle = TrialSettlementService(db_session)
    provider = InMemoryEventUpdateProvider([EventUpdate("X1", "finished", "home_win")])

    assert settle.settle_due(settled_at=NOW).unresolved == [bet.id]  # antes de la ingesta

    service.sync(provider)
    assert db_session.query(Settlement).count() == 0  # la ingesta no liquida
    assert db_session.get(Bet, bet.id).status == "pending"

    assert settle.settle_due(settled_at=NOW).settled == [bet.id]
    settlement = db_session.query(Settlement).one()
    assert settlement.status == expected
    assert (float(settlement.payout) if settlement.payout is not None else None) == payout
    assert db_session.get(Bet, bet.id).status == "settled"


def test_cancelled_event_is_voided_by_existing_resolver(db_session, service):
    """M: la ingesta no duplica la logica de void; la aplica el resolver."""
    event = _event(db_session)
    bet = _pending_bet(db_session, event)

    service.ingest([EventUpdate("X1", "cancelled")])
    db_session.expire_all()
    assert resolve_leg_result(db_session.get(Event, event.id), bet.legs[0]) == "void"
    assert db_session.query(Settlement).count() == 0

    TrialSettlementService(db_session).settle_due(settled_at=NOW)
    settlement = db_session.query(Settlement).one()
    assert settlement.status == "void" and float(settlement.payout) == 10.0
