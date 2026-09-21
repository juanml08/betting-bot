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
