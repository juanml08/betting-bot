from datetime import datetime, timezone

from app.db.models import Event
from app.db.repositories.bet_repository import BetRepository


def _make_event() -> Event:
    return Event(
        external_id="EV1",
        sport="soccer",
        league="Test League",
        competitor_home="Home FC",
        competitor_away="Away FC",
        start_time=datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc),
        status="scheduled",
        source="sample",
        result=None,
    )


def test_create_persists_bet_with_pending_status(db_session):
    event = _make_event()
    db_session.add(event)
    db_session.flush()

    repo = BetRepository(db_session)
    bet = repo.create(
        event_id=event.id,
        market_type="1x2",
        selection="home",
        odds_taken=1.9,
        stake=50.0,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
    )
    db_session.commit()

    assert bet.id is not None
    assert bet.status == "pending"
    assert bet.event_id == event.id
    assert float(bet.stake) == 50.0
    assert bet.opportunity_id is None


def test_get_returns_none_when_missing(db_session):
    assert BetRepository(db_session).get(999999) is None


def test_get_returns_persisted_bet(db_session):
    event = _make_event()
    db_session.add(event)
    db_session.flush()
    repo = BetRepository(db_session)
    created = repo.create(
        event_id=event.id,
        market_type="1x2",
        selection="home",
        odds_taken=1.9,
        stake=50.0,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
    )
    db_session.commit()

    fetched = repo.get(created.id)

    assert fetched is not None
    assert fetched.id == created.id


def test_settle_updates_status_and_settled_at(db_session):
    event = _make_event()
    db_session.add(event)
    db_session.flush()
    repo = BetRepository(db_session)
    bet = repo.create(
        event_id=event.id,
        market_type="1x2",
        selection="home",
        odds_taken=1.9,
        stake=50.0,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
    )
    db_session.commit()

    settled_at = datetime(2026, 1, 6, tzinfo=timezone.utc)
    updated = repo.settle(bet.id, status="won", settled_at=settled_at)

    # No se hace commit() aqui: SQLite no preserva tzinfo en columnas DateTime,
    # asi que tras un commit (que expira los atributos) el objeto se recargaria
    # como naive. Se verifica sobre el objeto recien flusheado en la sesion.
    assert updated is not None
    assert updated.status == "won"
    assert updated.settled_at == settled_at
    db_session.commit()


def test_settle_returns_none_when_bet_missing(db_session):
    assert BetRepository(db_session).settle(999999, status="won", settled_at=datetime.now(timezone.utc)) is None


def test_list_bets_filters_by_status_and_orders_newest_first(db_session):
    event = _make_event()
    db_session.add(event)
    db_session.flush()
    repo = BetRepository(db_session)

    older = repo.create(
        event_id=event.id,
        market_type="1x2",
        selection="home",
        odds_taken=1.9,
        stake=50.0,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    newer = repo.create(
        event_id=event.id,
        market_type="1x2",
        selection="away",
        odds_taken=2.5,
        stake=20.0,
        bankroll_at_time=950.0,
        placed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    repo.settle(newer.id, status="won", settled_at=datetime(2026, 1, 3, tzinfo=timezone.utc))
    db_session.commit()

    pending = repo.list_bets(status="pending")
    all_bets = repo.list_bets()

    assert [b.id for b in pending] == [older.id]
    assert [b.id for b in all_bets] == [newer.id, older.id]
