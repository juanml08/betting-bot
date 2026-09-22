from datetime import datetime, timezone

from app.db.models import Event, ProbabilityEstimateRecord
from app.db.repositories.opportunity_repository import OpportunityRepository
from app.domain.models import ValueOpportunity
from app.opportunities.opportunity_service import OpportunityCandidate


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


def _make_candidate() -> OpportunityCandidate:
    opp = ValueOpportunity(
        event_external_id="EV1",
        market_type="1x2",
        selection="home",
        bookmaker="SampleBook",
        odds_value=1.9,
        estimated_probability=0.6,
        implied_probability=0.5,
        edge=0.1,
        expected_value=0.14,
        kelly_fraction_suggested=0.2,
    )
    return OpportunityCandidate(opportunity=opp, suggested_stake=25.0)


def _make_probability_estimate(event_id: int) -> ProbabilityEstimateRecord:
    return ProbabilityEstimateRecord(
        event_id=event_id,
        market_type="1x2",
        selection="home",
        model_name="generic_rating",
        model_version="1",
        probability=0.6,
        computed_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
    )


def test_save_candidate_persists_all_value_metrics_and_links_event(db_session):
    event = _make_event()
    db_session.add(event)
    db_session.flush()

    candidate = _make_candidate()
    record = OpportunityRepository(db_session).save_candidate(candidate, event_id=event.id)
    db_session.commit()

    assert record.id is not None
    assert record.event_id == event.id
    assert record.event.external_id == "EV1"
    assert float(record.odds_value) == 1.9
    assert float(record.estimated_probability) == 0.6
    assert float(record.implied_probability) == 0.5
    assert float(record.edge) == 0.1
    assert float(record.expected_value) == 0.14
    assert float(record.kelly_fraction_suggested) == 0.2
    assert float(record.suggested_stake) == 25.0
    assert record.status == "candidate"
    assert record.probability_estimate_id is None


def test_save_candidate_links_probability_estimate_when_provided(db_session):
    event = _make_event()
    db_session.add(event)
    db_session.flush()
    estimate = _make_probability_estimate(event.id)
    db_session.add(estimate)
    db_session.flush()

    record = OpportunityRepository(db_session).save_candidate(
        _make_candidate(), event_id=event.id, probability_estimate_id=estimate.id
    )
    db_session.commit()

    assert record.probability_estimate_id == estimate.id


def test_save_candidate_without_probability_estimate_id_defaults_to_none(db_session):
    event = _make_event()
    db_session.add(event)
    db_session.flush()

    record = OpportunityRepository(db_session).save_candidate(_make_candidate(), event_id=event.id)
    db_session.commit()

    assert record.probability_estimate_id is None


def test_list_candidates_filters_by_status(db_session):
    event = _make_event()
    db_session.add(event)
    db_session.flush()
    repo = OpportunityRepository(db_session)

    saved = repo.save_candidate(_make_candidate(), event_id=event.id)
    saved.status = "rejected"
    repo.save_candidate(_make_candidate(), event_id=event.id)
    db_session.commit()

    candidates = repo.list_candidates(status="candidate")
    rejected = repo.list_candidates(status="rejected")

    assert len(candidates) == 1
    assert len(rejected) == 1
    assert rejected[0].id == saved.id


def test_list_candidates_orders_newest_first(db_session):
    event = _make_event()
    db_session.add(event)
    db_session.flush()
    repo = OpportunityRepository(db_session)

    first = repo.save_candidate(_make_candidate(), event_id=event.id)
    first.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    second = repo.save_candidate(_make_candidate(), event_id=event.id)
    second.created_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    db_session.commit()

    candidates = repo.list_candidates()

    assert [c.id for c in candidates] == [second.id, first.id]
