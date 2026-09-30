import pytest

from app.db.models import Opportunity


def test_list_opportunities_empty(client):
    response = client.get("/api/v1/opportunities")

    assert response.status_code == 200
    assert response.json() == []


def test_generate_opportunities_persists_candidates_with_valid_metrics(
    client_permissive_opportunities, db_session, seeded_events
):
    response = client_permissive_opportunities.post("/api/v1/opportunities/generate")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) > 0

    # Solo los eventos "scheduled" de los fixtures (S7, B7, T7) generan oportunidades.
    for candidate in payload:
        assert candidate["event_id"] in {seeded_events["S7"].id, seeded_events["B7"].id, seeded_events["T7"].id}
        assert 0.0 <= candidate["estimated_probability"] <= 1.0
        assert 0.0 <= candidate["implied_probability"] <= 1.0
        assert candidate["odds_value"] > 1.0
        assert candidate["kelly_fraction_suggested"] >= 0.0
        assert candidate["suggested_stake"] >= 0.0
        assert candidate["status"] == "candidate"
        # edge = estimada - implicita (ver ValueCalculator)
        expected_edge = candidate["estimated_probability"] - candidate["implied_probability"]
        assert candidate["edge"] == pytest.approx(expected_edge, abs=1e-4)

    # Se persistieron realmente en la base de datos, no solo en la respuesta.
    persisted = db_session.query(Opportunity).all()
    assert len(persisted) == len(payload)


def test_generate_opportunities_fails_when_event_not_in_db(client_permissive_opportunities):
    """Los eventos deben existir en la DB (via seed) antes de generar oportunidades;
    si el pipeline encuentra un evento sin persistir, el endpoint debe rechazarlo
    en vez de crear una oportunidad huerfana."""
    response = client_permissive_opportunities.post("/api/v1/opportunities/generate")

    assert response.status_code == 409


def test_list_opportunities_filtered_by_status(client, db_session, seeded_events):
    event = seeded_events["S7"]
    db_session.add(
        Opportunity(
            event_id=event.id,
            market_type="1x2",
            selection="home",
            bookmaker="SampleBook",
            odds_value=1.65,
            estimated_probability=0.7,
            implied_probability=0.6,
            edge=0.1,
            expected_value=0.05,
            kelly_fraction_suggested=0.1,
            suggested_stake=25.0,
            status="candidate",
            created_at=event.start_time,
        )
    )
    db_session.add(
        Opportunity(
            event_id=event.id,
            market_type="1x2",
            selection="away",
            bookmaker="SampleBook",
            odds_value=5.0,
            estimated_probability=0.3,
            implied_probability=0.2,
            edge=0.1,
            expected_value=0.05,
            kelly_fraction_suggested=0.1,
            suggested_stake=10.0,
            status="rejected",
            created_at=event.start_time,
        )
    )
    db_session.commit()

    response = client.get("/api/v1/opportunities", params={"status": "candidate"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["selection"] == "home"
    assert payload[0]["status"] == "candidate"


# --- Fase 5.12: ciclo de vida a traves del endpoint --------------------------


def test_generate_twice_with_same_observation_does_not_duplicate(
    client_permissive_opportunities, db_session, seeded_events
):
    first = client_permissive_opportunities.post("/api/v1/opportunities/generate").json()
    second = client_permissive_opportunities.post("/api/v1/opportunities/generate").json()

    assert db_session.query(Opportunity).count() == len(first)
    assert sorted(o["id"] for o in second) == sorted(o["id"] for o in first)
    assert all(o["version"] == 1 and o["status"] == "candidate" for o in second)


def test_generate_with_changed_odds_supersedes_previous_version(client, db_session, seeded_events):
    from datetime import datetime

    from app.api.deps import get_opportunity_service
    from app.domain.models import OddsQuote
    from app.filters.opportunity_filters import OpportunityFilterConfig, ThresholdOpportunityFilter
    from app.ingestion.providers.sample_data_provider import SampleDataProvider
    from app.main import app
    from app.models.generic_rating_model import GenericRatingModel
    from app.opportunities.opportunity_service import OpportunityService
    from app.risk.bankroll import FractionalKellyRiskManager, RiskConfig

    state = {"odds": 1.65, "at": datetime(2026, 1, 26, 17, 0)}

    class _Odds:
        def get_odds(self, external_id):
            if external_id != "S7":
                return []
            at, odds = state["at"], state["odds"]
            return [
                OddsQuote("S7", "1x2", "home", "SampleBook", odds, at),
                OddsQuote("S7", "1x2", "draw", "SampleBook", 3.75, at),
                OddsQuote("S7", "1x2", "away", "SampleBook", 5.0, at),
            ]

    app.dependency_overrides[get_opportunity_service] = lambda: OpportunityService(
        data_provider=SampleDataProvider(),
        odds_provider=_Odds(),
        probability_model=GenericRatingModel(),
        opportunity_filter=ThresholdOpportunityFilter(
            OpportunityFilterConfig(min_edge=-1.0, min_expected_value=-1.0, min_odds=1.0, max_odds=100.0)
        ),
        risk_manager=FractionalKellyRiskManager(RiskConfig(kelly_fraction=0.25, max_stake_pct_per_bet=0.05)),
    )
    try:
        client.post("/api/v1/opportunities/generate")
        state.update(odds=1.80, at=datetime(2026, 1, 26, 17, 1))
        payload = client.post("/api/v1/opportunities/generate").json()
    finally:
        app.dependency_overrides.pop(get_opportunity_service, None)

    home = [o for o in payload if o["selection"] == "home"][0]
    assert home["version"] == 2 and home["odds_value"] == 1.8
    db_session.expire_all()
    rows = db_session.query(Opportunity).filter_by(selection="home").order_by(Opportunity.version).all()
    assert [(r.version, r.status) for r in rows] == [(1, "superseded"), (2, "candidate")]
    assert rows[0].superseded_by_id == rows[1].id
    # draw y away no cambiaron: siguen en v1 (heartbeat)
    assert {o["version"] for o in payload if o["selection"] != "home"} == {1}
    assert db_session.query(Opportunity).count() == 4
