"""Los campos de decision de una Opportunity persistida no pueden mutarse via ORM
(defensa en profundidad; un UPDATE SQL directo no pasa por el validador)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Event, Opportunity

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)

_NEW_VALUES = {
    "event_id": 999,
    "market_type": "other",
    "selection": "away",
    "bookmaker": "other",
    "odds_value": 9.99,
    "estimated_probability": 0.99,
    "implied_probability": 0.99,
    "edge": 0.99,
    "expected_value": 0.99,
    "kelly_fraction_suggested": 0.99,
    "suggested_stake": 999.0,
    "created_at": NOW + timedelta(days=1),
}


@pytest.fixture()
def persisted(db_session) -> Opportunity:
    event = Event(
        external_id="EV1", sport="soccer", league="L", competitor_home="A", competitor_away="B",
        start_time=NOW + timedelta(hours=6), status="scheduled", source="sample",
    )
    db_session.add(event)
    db_session.flush()
    opp = Opportunity(
        event_id=event.id, market_type="1x2", selection="home", bookmaker="a", odds_value=2.0,
        estimated_probability=0.55, implied_probability=0.5, edge=0.05, expected_value=0.1,
        kelly_fraction_suggested=0.1, suggested_stake=10.0, status="candidate", created_at=NOW,
    )
    db_session.add(opp)
    db_session.commit()
    return opp


@pytest.mark.parametrize("field", sorted(_NEW_VALUES))
def test_decision_fields_cannot_be_reassigned_after_persist(db_session, persisted, field):
    with pytest.raises(ValueError, match="inmutable"):
        setattr(persisted, field, _NEW_VALUES[field])


def test_decision_fields_are_untouched_after_failed_mutation(db_session, persisted):
    with pytest.raises(ValueError):
        persisted.odds_value = 9.99
    db_session.commit()
    db_session.expire_all()

    assert float(db_session.get(Opportunity, persisted.id).odds_value) == 2.0


def test_lifecycle_fields_remain_mutable(db_session, persisted):
    persisted.status = "expired"
    persisted.last_observed_at = NOW + timedelta(minutes=1)
    persisted.superseded_at = NOW
    persisted.superseded_by_id = None
    db_session.commit()

    assert db_session.get(Opportunity, persisted.id).status == "expired"


def test_fields_are_assignable_while_the_instance_is_transient():
    opp = Opportunity(odds_value=2.0, estimated_probability=0.5)
    opp.odds_value = 2.1  # todavia no persistida: se permite
    assert opp.odds_value == 2.1


def test_defaults_for_version_and_last_observed_at(db_session, persisted):
    assert persisted.version == 1
    assert persisted.last_observed_at == NOW.replace(tzinfo=None)
    assert persisted.superseded_at is None and persisted.superseded_by_id is None
