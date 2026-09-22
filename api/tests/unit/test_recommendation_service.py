from datetime import datetime, timezone

import pytest

from app.db.models import Event, Opportunity, Recommendation, RecommendationOpportunity
from app.db.repositories.recommendation_repository import RecommendationRepository
from app.recommendations.recommendation_service import RecommendationService


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
def service(db_session) -> RecommendationService:
    return RecommendationService(RecommendationRepository(db_session))


@pytest.fixture()
def opportunities(db_session) -> list[Opportunity]:
    event = _make_event()
    db_session.add(event)
    db_session.flush()

    opps = [_make_opportunity(event.id, selection=s) for s in ("home", "draw", "away")]
    db_session.add_all(opps)
    db_session.flush()
    return opps


def test_simple_recommendation_with_exactly_one_opportunity(service, db_session, opportunities):
    recommendation = service.create_recommendation(
        strategy_name="value_bet_v1",
        strategy_params={"min_edge": 0.03},
        bet_type="simple",
        bankroll_at_recommendation=1000.0,
        opportunity_ids=[opportunities[0].id],
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    db_session.commit()

    assert recommendation.id is not None
    assert recommendation.bet_type == "simple"
    legs = db_session.query(RecommendationOpportunity).filter_by(recommendation_id=recommendation.id).all()
    assert len(legs) == 1
    assert legs[0].leg_order == 1
    assert legs[0].opportunity_id == opportunities[0].id


def test_compound_recommendation_with_two_opportunities(service, db_session, opportunities):
    recommendation = service.create_recommendation(
        strategy_name="parlay_v1",
        strategy_params={},
        bet_type="compound",
        bankroll_at_recommendation=1000.0,
        opportunity_ids=[opportunities[0].id, opportunities[1].id],
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    db_session.commit()

    legs = (
        db_session.query(RecommendationOpportunity)
        .filter_by(recommendation_id=recommendation.id)
        .order_by(RecommendationOpportunity.leg_order)
        .all()
    )
    assert [leg.opportunity_id for leg in legs] == [opportunities[0].id, opportunities[1].id]


def test_compound_recommendation_with_three_opportunities(service, db_session, opportunities):
    recommendation = service.create_recommendation(
        strategy_name="parlay_v1",
        strategy_params={},
        bet_type="compound",
        bankroll_at_recommendation=1000.0,
        opportunity_ids=[o.id for o in opportunities],
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    db_session.commit()

    legs = (
        db_session.query(RecommendationOpportunity)
        .filter_by(recommendation_id=recommendation.id)
        .order_by(RecommendationOpportunity.leg_order)
        .all()
    )
    assert [leg.leg_order for leg in legs] == [1, 2, 3]


def test_compound_with_zero_opportunities_is_rejected(service, db_session):
    with pytest.raises(ValueError):
        service.create_recommendation(
            strategy_name="parlay_v1",
            strategy_params={},
            bet_type="compound",
            bankroll_at_recommendation=1000.0,
            opportunity_ids=[],
            generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )


def test_compound_with_one_opportunity_is_rejected(service, db_session, opportunities):
    with pytest.raises(ValueError):
        service.create_recommendation(
            strategy_name="parlay_v1",
            strategy_params={},
            bet_type="compound",
            bankroll_at_recommendation=1000.0,
            opportunity_ids=[opportunities[0].id],
            generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )


def test_compound_with_four_opportunities_is_rejected(service, db_session, opportunities):
    fourth = _make_opportunity(opportunities[0].event_id, selection="over_2_5")
    db_session.add(fourth)
    db_session.flush()

    with pytest.raises(ValueError):
        service.create_recommendation(
            strategy_name="parlay_v1",
            strategy_params={},
            bet_type="compound",
            bankroll_at_recommendation=1000.0,
            opportunity_ids=[o.id for o in opportunities] + [fourth.id],
            generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )


def test_simple_with_zero_opportunities_is_rejected(service, db_session):
    with pytest.raises(ValueError):
        service.create_recommendation(
            strategy_name="value_bet_v1",
            strategy_params={},
            bet_type="simple",
            bankroll_at_recommendation=1000.0,
            opportunity_ids=[],
            generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )


def test_simple_with_two_opportunities_is_rejected(service, db_session, opportunities):
    with pytest.raises(ValueError):
        service.create_recommendation(
            strategy_name="value_bet_v1",
            strategy_params={},
            bet_type="simple",
            bankroll_at_recommendation=1000.0,
            opportunity_ids=[opportunities[0].id, opportunities[1].id],
            generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )


def test_duplicate_opportunity_in_same_recommendation_is_rejected(service, db_session, opportunities):
    with pytest.raises(ValueError):
        service.create_recommendation(
            strategy_name="parlay_v1",
            strategy_params={},
            bet_type="compound",
            bankroll_at_recommendation=1000.0,
            opportunity_ids=[opportunities[0].id, opportunities[0].id],
            generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )


def test_strategy_name_and_params_are_persisted_exactly(service, db_session, opportunities):
    params = {"min_edge": 0.03, "kelly_fraction": 0.25}
    recommendation = service.create_recommendation(
        strategy_name="value_bet_v1",
        strategy_params=params,
        bet_type="simple",
        bankroll_at_recommendation=1000.0,
        opportunity_ids=[opportunities[0].id],
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    db_session.commit()
    recommendation_id = recommendation.id

    # Mutar el dict original despues de crear la Recommendation no debe
    # afectar el snapshot ya persistido.
    params["min_edge"] = 0.99

    db_session.expire_all()
    reloaded = db_session.get(Recommendation, recommendation_id)
    assert reloaded.strategy_name == "value_bet_v1"
    assert reloaded.strategy_params == {"min_edge": 0.03, "kelly_fraction": 0.25}


def test_explanation_is_persisted(service, db_session, opportunities):
    recommendation = service.create_recommendation(
        strategy_name="value_bet_v1",
        strategy_params={},
        bet_type="simple",
        bankroll_at_recommendation=1000.0,
        opportunity_ids=[opportunities[0].id],
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        explanation="Edge de 10% sobre la cuota de SampleBook",
    )
    db_session.commit()

    assert recommendation.explanation == "Edge de 10% sobre la cuota de SampleBook"


def test_bankroll_at_recommendation_is_persisted(service, db_session, opportunities):
    recommendation = service.create_recommendation(
        strategy_name="value_bet_v1",
        strategy_params={},
        bet_type="simple",
        bankroll_at_recommendation=1234.56,
        opportunity_ids=[opportunities[0].id],
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    db_session.commit()

    assert float(recommendation.bankroll_at_recommendation) == 1234.56


def test_generated_at_is_persisted(service, db_session, opportunities):
    generated_at = datetime(2026, 3, 4, 12, 30, tzinfo=timezone.utc)
    recommendation = service.create_recommendation(
        strategy_name="value_bet_v1",
        strategy_params={},
        bet_type="simple",
        bankroll_at_recommendation=1000.0,
        opportunity_ids=[opportunities[0].id],
        generated_at=generated_at,
    )

    # Se verifica sobre el objeto recien flusheado: SQLite no preserva tzinfo
    # en columnas DateTime, asi que tras un commit (que expira los atributos)
    # se recargaria como naive (mismo comportamiento ya documentado en
    # tests/repositories/test_bet_repository.py).
    assert recommendation.generated_at == generated_at
    db_session.commit()


def test_later_changes_to_opportunity_do_not_alter_existing_recommendation(
    service, db_session, opportunities
):
    recommendation = service.create_recommendation(
        strategy_name="value_bet_v1",
        strategy_params={"min_edge": 0.03},
        bet_type="simple",
        bankroll_at_recommendation=1000.0,
        opportunity_ids=[opportunities[0].id],
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    db_session.commit()
    recommendation_id = recommendation.id

    opportunity = opportunities[0]
    opportunity.status = "rejected"
    opportunity.estimated_probability = 0.99
    db_session.commit()

    db_session.expire_all()
    reloaded = db_session.get(Recommendation, recommendation_id)
    assert reloaded.strategy_name == "value_bet_v1"
    assert reloaded.strategy_params == {"min_edge": 0.03}
    assert float(reloaded.bankroll_at_recommendation) == 1000.0

    leg = db_session.query(RecommendationOpportunity).filter_by(recommendation_id=recommendation_id).one()
    assert leg.opportunity_id == opportunity.id
