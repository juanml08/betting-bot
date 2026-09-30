from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Event, Opportunity, ProbabilityEstimateRecord
from app.db.repositories.opportunity_repository import OpportunityRepository
from app.domain.models import ValueOpportunity
from app.opportunities.opportunity_service import OpportunityCandidate

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
TTL = timedelta(minutes=3)


def _make_event(external_id="EV1", *, status="scheduled", start=None) -> Event:
    return Event(
        external_id=external_id,
        sport="soccer",
        league="Test League",
        competitor_home="Home FC",
        competitor_away="Away FC",
        start_time=start or NOW + timedelta(hours=6),
        status=status,
        source="sample",
        result=None,
    )


def _make_candidate(odds=1.9, prob=0.6) -> OpportunityCandidate:
    opp = ValueOpportunity(
        event_external_id="EV1",
        market_type="1x2",
        selection="home",
        bookmaker="samplebook",
        odds_value=odds,
        estimated_probability=prob,
        implied_probability=0.5,
        edge=0.1,
        expected_value=0.14,
        kelly_fraction_suggested=0.2,
    )
    return OpportunityCandidate(opportunity=opp, suggested_stake=25.0, captured_at=NOW)


def _add_event(db_session, **kwargs) -> Event:
    event = _make_event(**kwargs)
    db_session.add(event)
    db_session.flush()
    return event


def _version(repo, event, *, version=1, observed_at=NOW, selection="home", status="candidate"):
    record = repo.create_version(
        _make_candidate(),
        event_id=event.id,
        market_type="1x2",
        selection=selection,
        bookmaker="samplebook",
        version=version,
        observed_at=observed_at,
        created_at=NOW,
    )
    record.status = status
    return record


def test_create_version_persists_all_value_metrics_and_links_event(db_session):
    event = _add_event(db_session)

    record = OpportunityRepository(db_session).create_version(
        _make_candidate(),
        event_id=event.id,
        market_type="1x2",
        selection="home",
        bookmaker="samplebook",
        version=1,
        observed_at=NOW,
        created_at=NOW,
    )
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
    assert (record.status, record.version) == ("candidate", 1)
    assert record.last_observed_at == NOW.replace(tzinfo=None)
    assert record.probability_estimate_id is None


def test_create_version_links_probability_estimate_when_provided(db_session):
    event = _add_event(db_session)
    estimate = ProbabilityEstimateRecord(
        event_id=event.id, market_type="1x2", selection="home", model_name="generic_rating",
        model_version="1", probability=0.6, computed_at=NOW,
    )
    db_session.add(estimate)
    db_session.flush()

    record = OpportunityRepository(db_session).create_version(
        _make_candidate(), event_id=event.id, market_type="1x2", selection="home",
        bookmaker="samplebook", version=1, observed_at=NOW, created_at=NOW,
        probability_estimate_id=estimate.id,
    )
    db_session.commit()

    assert record.probability_estimate_id == estimate.id


def test_list_candidates_filters_by_status(db_session):
    event = _add_event(db_session)
    repo = OpportunityRepository(db_session)
    _version(repo, event, selection="home", status="rejected")
    _version(repo, event, selection="draw")
    db_session.commit()

    assert [o.selection for o in repo.list_candidates(status="candidate")] == ["draw"]
    assert [o.selection for o in repo.list_candidates(status="rejected")] == ["home"]


def test_list_candidates_orders_newest_first(db_session):
    event = _add_event(db_session)
    repo = OpportunityRepository(db_session)
    first = repo.create_version(
        _make_candidate(), event_id=event.id, market_type="1x2", selection="home",
        bookmaker="samplebook", version=1, observed_at=NOW, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = repo.create_version(
        _make_candidate(), event_id=event.id, market_type="1x2", selection="home",
        bookmaker="samplebook", version=2, observed_at=NOW, created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    db_session.commit()

    assert [c.id for c in repo.list_candidates()] == [second.id, first.id]


# --- list_eligible: TTL -----------------------------------------------------


def test_candidate_inside_ttl_is_eligible(db_session):
    repo = OpportunityRepository(db_session)
    record = _version(repo, _add_event(db_session), observed_at=NOW - timedelta(minutes=2))
    db_session.commit()

    assert [o.id for o in repo.list_eligible(now=NOW, ttl=TTL)] == [record.id]


def test_candidate_exactly_at_ttl_boundary_is_eligible(db_session):
    repo = OpportunityRepository(db_session)
    record = _version(repo, _add_event(db_session), observed_at=NOW - TTL)
    db_session.commit()

    assert [o.id for o in repo.list_eligible(now=NOW, ttl=TTL)] == [record.id]


def test_candidate_outside_ttl_is_not_eligible_even_though_status_is_candidate(db_session):
    repo = OpportunityRepository(db_session)
    record = _version(repo, _add_event(db_session), observed_at=NOW - TTL - timedelta(seconds=1))
    db_session.commit()

    assert repo.list_eligible(now=NOW, ttl=TTL) == []
    assert db_session.get(Opportunity, record.id).status == "candidate"  # sin job de limpieza


def test_ttl_is_evaluated_with_the_supplied_clock(db_session):
    repo = OpportunityRepository(db_session)
    _version(repo, _add_event(db_session), observed_at=NOW)
    db_session.commit()

    assert len(repo.list_eligible(now=NOW + TTL, ttl=TTL)) == 1
    assert repo.list_eligible(now=NOW + TTL + timedelta(seconds=1), ttl=TTL) == []
    assert repo.list_eligible(now=NOW + timedelta(hours=1), ttl=timedelta(hours=2)) != []


def test_heartbeat_extends_eligibility(db_session):
    repo = OpportunityRepository(db_session)
    record = _version(repo, _add_event(db_session), observed_at=NOW)
    db_session.commit()
    later = NOW + timedelta(minutes=10)
    assert repo.list_eligible(now=later, ttl=TTL) == []

    repo.heartbeat(record, later - timedelta(minutes=1))

    assert [o.id for o in repo.list_eligible(now=later, ttl=TTL)] == [record.id]


@pytest.mark.parametrize("status", ["superseded", "expired", "rejected"])
def test_non_candidate_status_is_not_eligible(db_session, status):
    repo = OpportunityRepository(db_session)
    _version(repo, _add_event(db_session), status=status)
    db_session.commit()

    assert repo.list_eligible(now=NOW, ttl=TTL) == []


# --- list_eligible: evento --------------------------------------------------


def test_scheduled_future_event_is_eligible(db_session):
    repo = OpportunityRepository(db_session)
    record = _version(repo, _add_event(db_session, start=NOW + timedelta(seconds=1)))
    db_session.commit()

    assert [o.id for o in repo.list_eligible(now=NOW, ttl=TTL)] == [record.id]


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(minutes=-1)])
def test_started_event_is_not_eligible(db_session, delta):
    repo = OpportunityRepository(db_session)
    _version(repo, _add_event(db_session, start=NOW + delta))
    db_session.commit()

    assert repo.list_eligible(now=NOW, ttl=TTL) == []


@pytest.mark.parametrize("status", ["cancelled", "live", "finished"])
def test_non_scheduled_event_is_not_eligible(db_session, status):
    repo = OpportunityRepository(db_session)
    _version(repo, _add_event(db_session, status=status))
    db_session.commit()

    assert repo.list_eligible(now=NOW, ttl=TTL) == []


def test_list_eligible_accepts_naive_and_aware_now(db_session):
    repo = OpportunityRepository(db_session)
    _version(repo, _add_event(db_session))
    db_session.commit()

    assert len(repo.list_eligible(now=NOW.replace(tzinfo=None), ttl=TTL)) == 1
    assert len(repo.list_eligible(now=NOW, ttl=TTL)) == 1


def test_list_eligible_filters_in_sql_and_returns_orm_rows_only_for_eligibles(db_session):
    repo = OpportunityRepository(db_session)
    event = _add_event(db_session)
    fresh = _version(repo, event, selection="home", observed_at=NOW)
    _version(repo, event, selection="draw", observed_at=NOW - timedelta(days=1))
    _version(repo, event, selection="away", status="superseded")
    db_session.commit()
    db_session.expire_all()

    eligible = repo.list_eligible(now=NOW, ttl=TTL)

    assert [o.id for o in eligible] == [fresh.id]
    assert len(db_session.identity_map) == 1 + 1  # solo la elegible y su Event (join), no todas las Opportunities
