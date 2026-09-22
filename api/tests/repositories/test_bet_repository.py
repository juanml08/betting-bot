from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import BetLeg, Event, Recommendation
from app.db.repositories.bet_repository import BetRepository


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


def _make_recommendation(db_session) -> Recommendation:
    recommendation = Recommendation(
        strategy_name="value_bet_v1",
        strategy_params={},
        bet_type="simple",
        bankroll_at_recommendation=1000.0,
        generated_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
    )
    db_session.add(recommendation)
    db_session.flush()
    return recommendation


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


def test_create_persists_simple_bet_with_one_leg(db_session):
    event = _make_event(db_session)
    repo = BetRepository(db_session)

    bet = repo.create(
        bet_type="simple",
        mode="real",
        stake=50.0,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        legs=[_leg(event.id)],
    )
    db_session.commit()

    assert bet.id is not None
    assert bet.status == "pending"
    assert bet.recommendation_id is None
    assert float(bet.stake) == 50.0
    assert len(bet.legs) == 1
    assert bet.legs[0].leg_order == 1
    assert bet.legs[0].result == "pending"
    assert float(bet.legs[0].odds_taken) == 1.9


def test_create_persists_compound_bet_with_ordered_legs(db_session):
    e1 = _make_event(db_session, "EV1")
    e2 = _make_event(db_session, "EV2")
    e3 = _make_event(db_session, "EV3")
    repo = BetRepository(db_session)

    bet = repo.create(
        bet_type="compound",
        mode="real",
        stake=20.0,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        legs=[
            _leg(e1.id, selection="home", odds_taken=1.8),
            _leg(e2.id, selection="away", odds_taken=1.7),
            _leg(e3.id, selection="draw", odds_taken=1.65),
        ],
    )
    db_session.commit()

    assert [leg.leg_order for leg in bet.legs] == [1, 2, 3]
    assert [leg.event_id for leg in bet.legs] == [e1.id, e2.id, e3.id]


def test_get_returns_none_when_missing(db_session):
    assert BetRepository(db_session).get(999999) is None


def test_get_returns_persisted_bet_with_legs(db_session):
    event = _make_event(db_session)
    repo = BetRepository(db_session)
    created = repo.create(
        bet_type="simple",
        mode="real",
        stake=50.0,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        legs=[_leg(event.id)],
    )
    db_session.commit()

    fetched = repo.get(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert len(fetched.legs) == 1


def test_list_bets_filters_by_status_and_orders_newest_first(db_session):
    event = _make_event(db_session)
    repo = BetRepository(db_session)

    older = repo.create(
        bet_type="simple",
        mode="real",
        stake=50.0,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        legs=[_leg(event.id)],
    )
    newer = repo.create(
        bet_type="simple",
        mode="real",
        stake=20.0,
        bankroll_at_time=950.0,
        placed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        legs=[_leg(event.id, selection="away")],
    )
    newer.status = "settled"
    db_session.commit()

    pending = repo.list_bets(status="pending")
    all_bets = repo.list_bets()

    assert [b.id for b in pending] == [older.id]
    assert [b.id for b in all_bets] == [newer.id, older.id]


def test_bet_leg_unique_constraint_on_bet_id_and_leg_order(db_session):
    event = _make_event(db_session)
    repo = BetRepository(db_session)
    bet = repo.create(
        bet_type="simple",
        mode="real",
        stake=50.0,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        legs=[_leg(event.id)],
    )
    db_session.commit()

    db_session.add(BetLeg(bet_id=bet.id, leg_order=1, **_leg(event.id, selection="away")))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_bet_leg_requires_valid_event_fk(db_session):
    repo = BetRepository(db_session)
    with pytest.raises(IntegrityError):
        repo.create(
            bet_type="simple",
            mode="real",
            stake=50.0,
            bankroll_at_time=1000.0,
            placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            legs=[_leg(999999)],
        )
    db_session.rollback()


def test_bet_can_reference_recommendation(db_session):
    event = _make_event(db_session)
    recommendation = _make_recommendation(db_session)
    repo = BetRepository(db_session)

    bet = repo.create(
        bet_type="simple",
        mode="real",
        stake=50.0,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        legs=[_leg(event.id)],
        recommendation_id=recommendation.id,
    )
    db_session.commit()

    assert bet.recommendation_id == recommendation.id


def test_recommendation_can_originate_at_most_one_bet(db_session):
    event = _make_event(db_session)
    recommendation = _make_recommendation(db_session)
    repo = BetRepository(db_session)

    repo.create(
        bet_type="simple",
        mode="real",
        stake=50.0,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        legs=[_leg(event.id)],
        recommendation_id=recommendation.id,
    )
    db_session.commit()

    with pytest.raises(IntegrityError):
        repo.create(
            bet_type="simple",
            mode="real",
            stake=10.0,
            bankroll_at_time=950.0,
            placed_at=datetime(2026, 1, 6, tzinfo=timezone.utc),
            legs=[_leg(event.id, selection="away")],
            recommendation_id=recommendation.id,
        )
    db_session.rollback()


def test_manual_bet_without_recommendation_is_allowed(db_session):
    event = _make_event(db_session)
    repo = BetRepository(db_session)

    bet = repo.create(
        bet_type="simple",
        mode="real",
        stake=50.0,
        bankroll_at_time=1000.0,
        placed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        legs=[_leg(event.id)],
    )
    db_session.commit()

    assert bet.recommendation_id is None
