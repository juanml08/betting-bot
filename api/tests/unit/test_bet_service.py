from datetime import datetime, timezone

import pytest

from app.bets.bet_service import BetService
from app.db.models import Event
from app.db.repositories.bet_repository import BetRepository
from app.db.repositories.recommendation_repository import RecommendationRepository


def _make_event(db_session, external_id="EV1") -> Event:
    event = Event(
        external_id=external_id,
        sport="soccer",
        league="Test League",
        competitor_home="Home FC",
        competitor_away="Away FC",
        start_time=datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc),
        status="scheduled",
        source="sample",
        result=None,
    )
    db_session.add(event)
    db_session.flush()
    return event


def _leg(event_id: int, **overrides) -> dict:
    leg = dict(
        event_id=event_id,
        market_type="1x2",
        selection="home",
        bookmaker="SampleBook",
        odds_taken=1.9,
    )
    leg.update(overrides)
    return leg


@pytest.fixture()
def service(db_session) -> BetService:
    return BetService(BetRepository(db_session), RecommendationRepository(db_session))


def _create(service, db_session, *, bet_type, legs, mode="real", recommendation_id=None):
    return service.create_bet(
        bet_type=bet_type,
        mode=mode,
        stake=50.0,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        legs=legs,
        recommendation_id=recommendation_id,
    )


def test_simple_with_one_leg_is_accepted(service, db_session):
    event = _make_event(db_session)
    bet = _create(service, db_session, bet_type="simple", legs=[_leg(event.id)])
    db_session.commit()

    assert bet.id is not None
    assert bet.bet_type == "simple"
    assert len(bet.legs) == 1


def test_compound_with_two_legs_is_accepted(service, db_session):
    e1, e2 = _make_event(db_session, "EV1"), _make_event(db_session, "EV2")
    bet = _create(service, db_session, bet_type="compound", legs=[_leg(e1.id), _leg(e2.id, selection="away")])
    db_session.commit()

    assert len(bet.legs) == 2


def test_compound_with_three_legs_is_accepted(service, db_session):
    events = [_make_event(db_session, f"EV{i}") for i in range(3)]
    legs = [_leg(e.id, selection=f"sel{i}") for i, e in enumerate(events)]
    bet = _create(service, db_session, bet_type="compound", legs=legs)
    db_session.commit()

    assert [leg.leg_order for leg in bet.legs] == [1, 2, 3]


def test_simple_with_zero_legs_is_rejected(service, db_session):
    with pytest.raises(ValueError):
        _create(service, db_session, bet_type="simple", legs=[])


def test_simple_with_two_legs_is_rejected(service, db_session):
    e1, e2 = _make_event(db_session, "EV1"), _make_event(db_session, "EV2")
    with pytest.raises(ValueError):
        _create(service, db_session, bet_type="simple", legs=[_leg(e1.id), _leg(e2.id)])


def test_compound_with_one_leg_is_rejected(service, db_session):
    event = _make_event(db_session)
    with pytest.raises(ValueError):
        _create(service, db_session, bet_type="compound", legs=[_leg(event.id)])


def test_compound_with_four_legs_is_rejected(service, db_session):
    events = [_make_event(db_session, f"EV{i}") for i in range(4)]
    legs = [_leg(e.id, selection=f"sel{i}") for i, e in enumerate(events)]
    with pytest.raises(ValueError):
        _create(service, db_session, bet_type="compound", legs=legs)


def test_two_legs_of_same_event_is_rejected(service, db_session):
    event = _make_event(db_session)
    with pytest.raises(ValueError):
        _create(
            service,
            db_session,
            bet_type="compound",
            legs=[_leg(event.id, selection="home"), _leg(event.id, selection="away")],
        )


def test_invalid_bet_type_is_rejected(service, db_session):
    event = _make_event(db_session)
    with pytest.raises(ValueError):
        _create(service, db_session, bet_type="parlay", legs=[_leg(event.id)])


def test_invalid_mode_is_rejected(service, db_session):
    event = _make_event(db_session)
    with pytest.raises(ValueError):
        _create(service, db_session, bet_type="simple", legs=[_leg(event.id)], mode="fake")


def test_trial_mode_is_accepted(service, db_session):
    event = _make_event(db_session)
    bet = _create(service, db_session, bet_type="simple", legs=[_leg(event.id)], mode="trial")
    db_session.commit()

    assert bet.mode == "trial"


def test_nonexistent_recommendation_is_rejected(service, db_session):
    event = _make_event(db_session)
    with pytest.raises(ValueError):
        _create(service, db_session, bet_type="simple", legs=[_leg(event.id)], recommendation_id=999999)
