from datetime import datetime, timezone

from app.db.models import Event


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


def test_list_events_empty(client):
    response = client.get("/api/v1/events")

    assert response.status_code == 200
    assert response.json() == []


def test_list_events_returns_persisted_data(client, db_session):
    event = _make_event()
    db_session.add(event)
    db_session.commit()

    response = client.get("/api/v1/events")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["external_id"] == "EV1"
    assert payload[0]["sport"] == "soccer"
    assert payload[0]["competitor_home"] == "Home FC"
    assert payload[0]["status"] == "scheduled"
    assert payload[0]["result"] is None


def test_list_events_filtered_by_sport(client, db_session):
    db_session.add_all(
        [
            _make_event(external_id="EV1", sport="soccer"),
            _make_event(external_id="EV2", sport="basketball"),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/events", params={"sport": "basketball"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["external_id"] == "EV2"


def test_list_events_ordered_by_start_time(client, db_session):
    db_session.add_all(
        [
            _make_event(external_id="LATER", start_time=datetime(2026, 2, 1, tzinfo=timezone.utc)),
            _make_event(external_id="EARLIER", start_time=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/events")

    payload = response.json()
    assert [e["external_id"] for e in payload] == ["EARLIER", "LATER"]
