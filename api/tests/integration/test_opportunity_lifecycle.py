"""Fase 5.12 - OpportunityLifecycleService: versionado, heartbeat, anti-desorden,
expiracion y concurrencia sobre una BD real (SQLite en memoria)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Event, Opportunity
from app.db.repositories.opportunity_repository import OpportunityRepository
from app.domain.models import ValueOpportunity
from app.opportunities.opportunity_lifecycle_service import (
    OpportunityLifecycleService,
    SlotAction,
    UnknownEventError,
)
from app.opportunities.opportunity_service import (
    ObservedSlot,
    OpportunityCandidate,
    OpportunityObservation,
)
from app.opportunities.slot import SlotKey

T0 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
START = datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc)
PERSIST_AT = datetime(2026, 1, 5, 12, 30, tzinfo=timezone.utc)


def _minutes(n: int) -> datetime:
    return T0 + timedelta(minutes=n)


@pytest.fixture()
def event(db_session) -> Event:
    e = Event(
        external_id="EV1", sport="soccer", league="L", competitor_home="A", competitor_away="B",
        start_time=START, status="scheduled", source="sample",
    )
    db_session.add(e)
    db_session.commit()
    return e


@pytest.fixture()
def lifecycle(db_session) -> OpportunityLifecycleService:
    return OpportunityLifecycleService(db_session, clock=lambda: PERSIST_AT)


def _cand(
    odds=2.0, prob=0.55, *, at=T0, ext="EV1", bookmaker="BookA", selection="home", market="1x2"
) -> OpportunityCandidate:
    opp = ValueOpportunity(
        event_external_id=ext, market_type=market, selection=selection, bookmaker=bookmaker,
        odds_value=odds, estimated_probability=prob, implied_probability=1 / odds,
        edge=prob - 1 / odds, expected_value=prob * odds - 1, kelly_fraction_suggested=0.1,
    )
    return OpportunityCandidate(opportunity=opp, suggested_stake=10.0, captured_at=at)


def _observe(*candidates, non_qualifying=(), evaluated=None, ext="EV1", at=None):
    """Observacion de una pasada que evaluo el evento `ext` (salvo evaluated={})."""
    if evaluated is None:
        times = [c.captured_at for c in candidates] + [s.captured_at for s in non_qualifying]
        evaluated = {ext: at or (max(times) if times else T0)}
    return OpportunityObservation(
        candidates=list(candidates), non_qualifying=list(non_qualifying), evaluated_events=evaluated
    )


def _not_qualifying(at, *, ext="EV1", bookmaker="BookA", selection="home", market="1x2"):
    return ObservedSlot(SlotKey.of(ext, market, selection, bookmaker), at)


def _rows(db_session, **filters) -> list[Opportunity]:
    db_session.expire_all()
    return (
        db_session.query(Opportunity).filter_by(**filters).order_by(Opportunity.version).all()
    )


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


# --- Identidad --------------------------------------------------------------


def test_same_slot_reuses_the_same_version_chain(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(2.0, at=_minutes(0))))
    lifecycle.apply(_observe(_cand(2.2, at=_minutes(1))))
    lifecycle.apply(_observe(_cand(2.4, at=_minutes(2))))

    assert [o.version for o in _rows(db_session)] == [1, 2, 3]


def test_different_bookmakers_are_independent_slots(lifecycle, db_session, event):
    lifecycle.apply(
        _observe(_cand(2.2, bookmaker="A"), _cand(2.35, bookmaker="B"), _cand(2.1, bookmaker="C"))
    )
    lifecycle.apply(
        _observe(
            _cand(2.5, bookmaker="A", at=_minutes(1)),
            _cand(2.35, bookmaker="B", at=_minutes(1)),
            _cand(2.1, bookmaker="C", at=_minutes(1)),
        )
    )

    by_book = {o.bookmaker: [] for o in _rows(db_session)}
    for o in _rows(db_session):
        by_book[o.bookmaker].append((o.version, o.status))
    assert by_book["a"] == [(1, "superseded"), (2, "candidate")]
    assert by_book["b"] == [(1, "candidate")] and by_book["c"] == [(1, "candidate")]


@pytest.mark.parametrize("variant", [" Bet365 ", "bet365", "BET365", "\tBeT365\n"])
def test_normalization_avoids_duplicates_by_casing_and_whitespace(lifecycle, db_session, event, variant):
    lifecycle.apply(_observe(_cand(bookmaker="bet365", at=_minutes(0))))
    lifecycle.apply(_observe(_cand(bookmaker=variant, at=_minutes(1))))

    rows = _rows(db_session)
    assert len(rows) == 1 and rows[0].bookmaker == "bet365"


def test_market_and_selection_are_normalized(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(market=" 1X2 ", selection="Home ")))
    row = _rows(db_session)[0]
    assert (row.market_type, row.selection) == ("1x2", "home")


# --- Primera version --------------------------------------------------------


def test_missing_slot_creates_v1_candidate(lifecycle, db_session, event):
    result = lifecycle.apply(_observe(_cand(2.0, 0.55, at=_minutes(3))))

    row = _rows(db_session)[0]
    assert (row.version, row.status) == (1, "candidate")
    assert row.last_observed_at == _naive(_minutes(3))  # captured_at, no created_at
    assert row.created_at == _naive(PERSIST_AT)
    assert row.superseded_at is None and row.superseded_by_id is None
    assert [o.action for o in result.outcomes] == [SlotAction.CREATED]


# --- Nueva version ----------------------------------------------------------


@pytest.mark.parametrize(
    "odds,prob", [(2.5, 0.55), (2.0, 0.60), (2.5, 0.60)], ids=["odds", "probability", "both"]
)
def test_change_creates_new_version_and_supersedes_previous(lifecycle, db_session, event, odds, prob):
    lifecycle.apply(_observe(_cand(2.0, 0.55, at=_minutes(0))))
    v1_before = {
        c: getattr(_rows(db_session)[0], c)
        for c in ("odds_value", "estimated_probability", "implied_probability", "edge",
                  "expected_value", "kelly_fraction_suggested", "suggested_stake", "created_at")
    }

    result = lifecycle.apply(_observe(_cand(odds, prob, at=_minutes(1))))

    v1, v2 = _rows(db_session)
    assert (v1.version, v1.status) == (1, "superseded")
    assert (v2.version, v2.status) == (2, "candidate")
    assert v1.superseded_by_id == v2.id
    assert v1.superseded_at == _naive(_minutes(1))
    assert v2.last_observed_at == _naive(_minutes(1))
    assert {c: getattr(v1, c) for c in v1_before} == v1_before  # snapshot intacto
    assert float(v2.odds_value) == odds and float(v2.estimated_probability) == prob
    assert [o.action for o in result.outcomes] == [SlotAction.NEW_VERSION]
    assert sum(1 for o in _rows(db_session) if o.status == "candidate") == 1


# --- Heartbeat --------------------------------------------------------------


def test_same_odds_and_probability_only_updates_last_observed_at(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(2.0, 0.55, at=_minutes(0))))

    result = lifecycle.apply(_observe(_cand(2.0, 0.55, at=_minutes(2))))

    rows = _rows(db_session)
    assert len(rows) == 1
    assert rows[0].last_observed_at == _naive(_minutes(2))
    assert rows[0].created_at == _naive(PERSIST_AT)
    assert [o.action for o in result.outcomes] == [SlotAction.HEARTBEAT]


def test_float_noise_below_storage_precision_is_a_heartbeat(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(2.0, 0.55, at=_minutes(0))))
    lifecycle.apply(_observe(_cand(2.0000001, 0.5500000001, at=_minutes(1))))
    assert len(_rows(db_session)) == 1


def test_heartbeat_is_monotonic_at_repository_level(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(at=_minutes(5))))
    row = _rows(db_session)[0]
    repo = OpportunityRepository(db_session)

    assert repo.heartbeat(row, _minutes(2)) is False  # retroceder no cambia nada
    assert repo.heartbeat(row, _minutes(5)) is False  # igual tampoco
    assert repo.heartbeat(row, _minutes(6)) is True
    assert row.last_observed_at == _naive(_minutes(6))


# --- Anti-desorden ----------------------------------------------------------


def test_older_observation_is_ignored_completely(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(2.0, 0.55, at=_minutes(10))))

    result = lifecycle.apply(_observe(_cand(3.0, 0.70, at=_minutes(5))))

    rows = _rows(db_session)
    assert len(rows) == 1
    assert rows[0].status == "candidate"
    assert float(rows[0].odds_value) == 2.0 and float(rows[0].estimated_probability) == 0.55
    assert rows[0].last_observed_at == _naive(_minutes(10))
    assert [o.action for o in result.outcomes] == [SlotAction.IGNORED_STALE]


def test_observation_with_same_timestamp_has_no_effect(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(2.0, 0.55, at=_minutes(10))))

    result = lifecycle.apply(_observe(_cand(3.0, 0.70, at=_minutes(10))))

    assert len(_rows(db_session)) == 1 and float(_rows(db_session)[0].odds_value) == 2.0
    assert [o.action for o in result.outcomes] == [SlotAction.IGNORED_STALE]


def test_old_observation_cannot_resurrect_an_expired_slot(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(2.5, at=_minutes(0))))
    lifecycle.apply(_observe(non_qualifying=[_not_qualifying(_minutes(10))]))
    assert _rows(db_session)[0].status == "expired"

    lifecycle.apply(_observe(_cand(2.5, at=_minutes(5))))  # llega tarde

    rows = _rows(db_session)
    assert len(rows) == 1 and rows[0].status == "expired"


def test_stale_close_does_not_expire_a_newer_candidate(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(2.5, at=_minutes(10))))

    result = lifecycle.apply(_observe(non_qualifying=[_not_qualifying(_minutes(5))]))

    assert _rows(db_session)[0].status == "candidate"
    assert [o.action for o in result.outcomes] == [SlotAction.IGNORED_STALE]


# --- Expiracion -------------------------------------------------------------


def test_candidate_that_stops_qualifying_is_expired_without_new_row(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(2.5, at=_minutes(0))))

    result = lifecycle.apply(_observe(non_qualifying=[_not_qualifying(_minutes(1))]))

    rows = _rows(db_session)
    assert len(rows) == 1 and rows[0].status == "expired"
    assert rows[0].superseded_by_id is None
    assert [o.action for o in result.outcomes] == [SlotAction.EXPIRED]
    assert not [o for o in rows if o.status == "candidate"]


def test_bookmaker_missing_from_evaluated_event_is_expired(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(2.2, bookmaker="A", at=_minutes(0)), _cand(2.3, bookmaker="B", at=_minutes(0))))

    # A pasada siguiente solo trae B: A desaparecio del evento evaluado.
    result = lifecycle.apply(_observe(_cand(2.3, bookmaker="B", at=_minutes(1))))

    by_book = {o.bookmaker: o.status for o in _rows(db_session)}
    assert by_book == {"a": "expired", "b": "candidate"}
    assert result.count(SlotAction.EXPIRED) == 1 and result.count(SlotAction.HEARTBEAT) == 1


def test_event_evaluated_with_no_quotes_expires_its_slots(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(2.2, at=_minutes(0))))

    lifecycle.apply(_observe(evaluated={"EV1": _minutes(1)}))

    assert _rows(db_session)[0].status == "expired"


def test_events_not_evaluated_in_the_pass_are_untouched(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(2.2, at=_minutes(0))))

    lifecycle.apply(_observe(evaluated={}))

    assert _rows(db_session)[0].status == "candidate"


def test_close_is_idempotent(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(2.5, at=_minutes(0))))
    row = _rows(db_session)[0]
    repo = OpportunityRepository(db_session)

    assert repo.mark_expired(row, _minutes(1)) is True
    assert repo.mark_expired(row, _minutes(2)) is False
    db_session.commit()
    assert _rows(db_session)[0].status == "expired"


def test_new_candidate_after_expiry_opens_next_version(lifecycle, db_session, event):
    lifecycle.apply(_observe(_cand(2.5, at=_minutes(0))))
    lifecycle.apply(_observe(non_qualifying=[_not_qualifying(_minutes(1))]))

    lifecycle.apply(_observe(_cand(2.5, at=_minutes(2))))

    v1, v2 = _rows(db_session)
    assert (v1.status, v2.status, v2.version) == ("expired", "candidate", 2)
    assert v1.superseded_by_id is None  # expired no es superseded


# --- Evento desconocido -----------------------------------------------------


def test_unknown_event_for_a_candidate_fails_before_writing(lifecycle, db_session, event):
    obs = _observe(_cand(ext="EV1"), _cand(ext="NOPE", selection="away"), evaluated={"EV1": T0, "NOPE": T0})

    with pytest.raises(UnknownEventError) as exc:
        lifecycle.apply(obs)

    assert exc.value.external_ids == ["NOPE"]
    assert db_session.query(Opportunity).count() == 0


def test_candidate_without_captured_at_is_rejected(lifecycle, db_session, event):
    candidate = _cand()
    candidate.captured_at = None
    with pytest.raises(ValueError, match="captured_at"):
        lifecycle.apply(_observe(candidate, evaluated={"EV1": T0}))
    assert db_session.query(Opportunity).count() == 0


# --- Concurrencia -----------------------------------------------------------


def _first_read_sees_nothing(monkeypatch):
    """Simula que la lectura del slot ocurrio antes de que otro proceso
    insertara la version (read-then-insert entrelazado)."""
    original = OpportunityRepository.find_latest_version
    calls = {"n": 0}

    def fake(self, **kwargs):
        calls["n"] += 1
        return None if calls["n"] == 1 else original(self, **kwargs)

    monkeypatch.setattr(OpportunityRepository, "find_latest_version", fake)
    return calls


def test_racing_creation_of_same_version_retries_and_resolves_as_heartbeat(
    lifecycle, db_session, event, monkeypatch
):
    lifecycle.apply(_observe(_cand(2.0, 0.55, at=_minutes(0))))  # "el otro proceso" ya inserto v1
    calls = _first_read_sees_nothing(monkeypatch)

    result = lifecycle.apply(_observe(_cand(2.0, 0.55, at=_minutes(1))))

    rows = _rows(db_session)
    assert [(o.version, o.status) for o in rows] == [(1, "candidate")]  # sin v1 duplicada
    assert rows[0].last_observed_at == _naive(_minutes(1))
    assert [o.action for o in result.outcomes] == [SlotAction.HEARTBEAT]
    assert calls["n"] >= 2  # releyo tras el rollback


def test_racing_creation_of_same_version_retries_and_resolves_as_new_version(
    lifecycle, db_session, event, monkeypatch
):
    lifecycle.apply(_observe(_cand(2.0, 0.55, at=_minutes(0))))
    _first_read_sees_nothing(monkeypatch)

    result = lifecycle.apply(_observe(_cand(2.4, 0.55, at=_minutes(1))))

    assert [(o.version, o.status) for o in _rows(db_session)] == [(1, "superseded"), (2, "candidate")]
    assert [o.action for o in result.outcomes] == [SlotAction.NEW_VERSION]


def test_unique_constraint_rejects_two_rows_with_same_slot_and_version(db_session, event):
    repo = OpportunityRepository(db_session)
    kwargs = dict(
        event_id=event.id, market_type="1x2", selection="home", bookmaker="a",
        version=1, observed_at=T0, created_at=T0,
    )
    repo.create_version(_cand(), **kwargs)
    with pytest.raises(IntegrityError):
        repo.create_version(_cand(2.4), **kwargs)
    db_session.rollback()


def test_persistent_conflict_is_raised_after_max_attempts(db_session, event, monkeypatch):
    service = OpportunityLifecycleService(db_session, clock=lambda: PERSIST_AT, max_attempts=2)
    service.apply(_observe(_cand(at=_minutes(0))))
    monkeypatch.setattr(OpportunityRepository, "find_latest_version", lambda self, **kw: None)

    with pytest.raises(IntegrityError):
        service.apply(_observe(_cand(at=_minutes(1))))

    monkeypatch.undo()
    assert len(_rows(db_session)) == 1
