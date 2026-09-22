from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Event, Opportunity, RecommendationOpportunity
from app.db.repositories.recommendation_repository import RecommendationRepository


def _make_event(external_id="EV1") -> Event:
    return Event(
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


def _make_opportunity(event_id: int, selection="home") -> Opportunity:
    return Opportunity(
        event_id=event_id,
        market_type="1x2",
        selection=selection,
        bookmaker="SampleBook",
        odds_value=1.9,
        estimated_probability=0.6,
        implied_probability=0.5,
        edge=0.1,
        expected_value=0.14,
        kelly_fraction_suggested=0.2,
        suggested_stake=25.0,
        status="candidate",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture()
def opportunities(db_session) -> list[Opportunity]:
    event = _make_event()
    db_session.add(event)
    db_session.flush()

    opps = [_make_opportunity(event.id, selection=s) for s in ("home", "draw", "away")]
    db_session.add_all(opps)
    db_session.flush()
    return opps


def test_create_persists_recommendation_and_legs_in_order(db_session, opportunities):
    repo = RecommendationRepository(db_session)

    recommendation = repo.create(
        strategy_name="value_bet_v1",
        strategy_params={"min_edge": 0.03},
        bet_type="compound",
        bankroll_at_recommendation=1000.0,
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        opportunity_ids=[opportunities[1].id, opportunities[0].id],
        explanation="edge combinado",
    )
    db_session.commit()

    assert recommendation.id is not None
    legs = (
        db_session.query(RecommendationOpportunity)
        .filter_by(recommendation_id=recommendation.id)
        .order_by(RecommendationOpportunity.leg_order)
        .all()
    )
    assert [leg.opportunity_id for leg in legs] == [opportunities[1].id, opportunities[0].id]
    assert [leg.leg_order for leg in legs] == [1, 2]


def test_get_returns_recommendation_with_its_opportunities_via_legs(db_session, opportunities):
    repo = RecommendationRepository(db_session)
    created = repo.create(
        strategy_name="value_bet_v1",
        strategy_params={},
        bet_type="simple",
        bankroll_at_recommendation=1000.0,
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        opportunity_ids=[opportunities[0].id],
    )
    db_session.commit()

    fetched = repo.get(created.id)

    assert fetched is not None
    assert len(fetched.legs) == 1
    assert fetched.legs[0].opportunity.id == opportunities[0].id


def test_get_returns_none_when_missing(db_session):
    assert RecommendationRepository(db_session).get(999999) is None


def test_unique_constraint_rejects_duplicate_leg_order(db_session, opportunities):
    repo = RecommendationRepository(db_session)
    created = repo.create(
        strategy_name="value_bet_v1",
        strategy_params={},
        bet_type="simple",
        bankroll_at_recommendation=1000.0,
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        opportunity_ids=[opportunities[0].id],
    )
    db_session.commit()

    db_session.add(
        RecommendationOpportunity(
            recommendation_id=created.id,
            opportunity_id=opportunities[1].id,
            leg_order=1,  # ya usado por la leg creada arriba
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_unique_constraint_rejects_duplicate_opportunity(db_session, opportunities):
    repo = RecommendationRepository(db_session)
    created = repo.create(
        strategy_name="value_bet_v1",
        strategy_params={},
        bet_type="simple",
        bankroll_at_recommendation=1000.0,
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        opportunity_ids=[opportunities[0].id],
    )
    db_session.commit()

    db_session.add(
        RecommendationOpportunity(
            recommendation_id=created.id,
            opportunity_id=opportunities[0].id,  # ya vinculada arriba
            leg_order=2,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_invalid_opportunity_id_is_rejected_by_db_fk(db_session, opportunities):
    repo = RecommendationRepository(db_session)

    with pytest.raises(IntegrityError):
        repo.create(
            strategy_name="value_bet_v1",
            strategy_params={},
            bet_type="simple",
            bankroll_at_recommendation=1000.0,
            generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            opportunity_ids=[999999],
        )
    db_session.rollback()
