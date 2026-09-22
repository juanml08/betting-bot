from datetime import datetime, timezone

from app.db.models import Event
from app.db.repositories.event_repository import EventRepository


def _make_event(**overrides) -> Event:
    defaults = dict(
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
    defaults.update(overrides)
    return Event(**defaults)


def test_list_events_returns_all_when_no_filter(db_session):
    db_session.add_all([_make_event(external_id="EV1", sport="soccer"), _make_event(external_id="EV2", sport="tennis")])
    db_session.commit()

    events = EventRepository(db_session).list_events()

    assert {e.external_id for e in events} == {"EV1", "EV2"}


def test_list_events_filters_by_sport(db_session):
    db_session.add_all([_make_event(external_id="EV1", sport="soccer"), _make_event(external_id="EV2", sport="tennis")])
    db_session.commit()

    events = EventRepository(db_session).list_events(sport="tennis")

    assert [e.external_id for e in events] == ["EV2"]


def test_list_events_orders_by_start_time(db_session):
    db_session.add_all(
        [
            _make_event(external_id="LATER", start_time=datetime(2026, 3, 1, tzinfo=timezone.utc)),
            _make_event(external_id="EARLIER", start_time=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ]
    )
    db_session.commit()

    events = EventRepository(db_session).list_events()

    assert [e.external_id for e in events] == ["EARLIER", "LATER"]


def test_get_by_external_id_found(db_session):
    db_session.add(_make_event(external_id="EV1"))
    db_session.commit()

    event = EventRepository(db_session).get_by_external_id("EV1")

    assert event is not None
    assert event.external_id == "EV1"


def test_get_by_external_id_not_found_returns_none(db_session):
    event = EventRepository(db_session).get_by_external_id("DOES_NOT_EXIST")

    assert event is None
