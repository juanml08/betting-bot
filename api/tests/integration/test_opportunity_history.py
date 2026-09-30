"""Una Recommendation/Bet historica conserva su snapshot aunque llegue una version nueva."""

from datetime import datetime, timedelta, timezone

from app.db.models import BetLeg, Event, Opportunity, RecommendationOpportunity
from app.domain.models import ValueOpportunity
from app.opportunities.opportunity_lifecycle_service import OpportunityLifecycleService
from app.opportunities.opportunity_service import OpportunityCandidate, OpportunityObservation
from app.risk.bankroll import FractionalKellyRiskManager, RiskConfig
from app.trials.trial_service import TrialService

T0 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
START = datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc)


def _observation(odds: float, at: datetime) -> OpportunityObservation:
    opp = ValueOpportunity(
        event_external_id="EV1", market_type="1x2", selection="home", bookmaker="BookA",
        odds_value=odds, estimated_probability=0.6, implied_probability=1 / odds,
        edge=0.6 - 1 / odds, expected_value=0.6 * odds - 1, kelly_fraction_suggested=0.2,
    )
    return OpportunityObservation(
        candidates=[OpportunityCandidate(opp, 10.0, captured_at=at)], evaluated_events={"EV1": at}
    )


def _setup(db_session):
    db_session.add(
        Event(
            external_id="EV1", sport="soccer", league="L", competitor_home="A", competitor_away="B",
            start_time=START, status="scheduled", source="sample",
        )
    )
    db_session.commit()
    lifecycle = OpportunityLifecycleService(db_session, clock=lambda: T0)
    trial = TrialService(
        db_session, FractionalKellyRiskManager(RiskConfig(kelly_fraction=0.25, max_stake_pct_per_bet=0.05))
    )
    return lifecycle, trial


def test_recommendation_keeps_pointing_to_v1_snapshot_after_v2(db_session):
    lifecycle, trial = _setup(db_session)

    lifecycle.apply(_observation(2.0, T0))
    result = trial.run_cycle(placed_at=T0, bankroll=1000.0)
    assert result.status == "executed"
    v1_id = db_session.query(Opportunity).one().id

    lifecycle.apply(_observation(2.4, T0 + timedelta(minutes=1)))

    db_session.expire_all()
    v1 = db_session.get(Opportunity, v1_id)
    v2 = db_session.query(Opportunity).filter_by(version=2).one()
    assert v1.status == "superseded" and v1.superseded_by_id == v2.id
    assert float(v1.odds_value) == 2.0  # snapshot de decision intacto
    assert db_session.query(RecommendationOpportunity).one().opportunity_id == v1_id
    assert float(db_session.query(BetLeg).one().odds_taken) == 2.0
    # El uso se determina por RecommendationOpportunity/Bet, no por un status 'used'.
    assert v2.status == "candidate"


def test_superseded_version_is_not_eligible_only_current_reaches_the_engine(db_session):
    lifecycle, trial = _setup(db_session)

    lifecycle.apply(_observation(2.5, T0))
    lifecycle.apply(_observation(2.0, T0 + timedelta(minutes=1)))  # la cuota vieja, mas alta, queda superseded

    result = trial.run_cycle(placed_at=T0 + timedelta(minutes=1), bankroll=1000.0)

    v2 = db_session.query(Opportunity).filter_by(version=2).one()
    assert result.eligible_opportunity_ids == [v2.id]
    assert float(result.bet.legs[0].odds_taken) == 2.0
