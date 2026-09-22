from datetime import datetime, timezone

from app.db.models import BankrollTransaction, Bet, Recommendation


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


def _bet_payload(event_id: int, **overrides) -> dict:
    payload = dict(
        bet_type="simple",
        stake=50.0,
        legs=[_leg(event_id)],
        recommendation_id=None,
        notes=None,
    )
    payload.update(overrides)
    return payload


def test_register_simple_bet_persists_and_updates_bankroll(client, db_session, seeded_events):
    event = seeded_events["S1"]

    response = client.post("/api/v1/bets", json=_bet_payload(event.id))

    assert response.status_code == 201
    payload = response.json()
    assert payload["bet_type"] == "simple"
    assert payload["mode"] == "real"
    assert payload["status"] == "pending"
    assert payload["stake"] == 50.0
    assert payload["bankroll_at_time"] == 1000.0
    assert len(payload["legs"]) == 1
    assert payload["legs"][0]["event_id"] == event.id
    assert payload["legs"][0]["result"] == "pending"
    assert payload["settlement"] is None

    persisted_bet = db_session.query(Bet).filter_by(id=payload["id"]).one()
    assert persisted_bet.status == "pending"
    assert float(persisted_bet.stake) == 50.0

    transactions = db_session.query(BankrollTransaction).all()
    assert len(transactions) == 1
    assert transactions[0].reason == "bet_placed"
    assert float(transactions[0].amount) == -50.0
    assert float(transactions[0].balance_after) == 950.0
    assert transactions[0].related_bet_id == persisted_bet.id


def test_register_compound_bet_with_two_legs(client, db_session, seeded_events):
    e1, e2 = seeded_events["S1"], seeded_events["S2"]

    response = client.post(
        "/api/v1/bets",
        json=_bet_payload(
            e1.id,
            bet_type="compound",
            stake=20.0,
            legs=[_leg(e1.id, odds_taken=1.8), _leg(e2.id, odds_taken=1.7, selection="away")],
        ),
    )

    assert response.status_code == 201
    payload = response.json()
    assert len(payload["legs"]) == 2
    assert [leg["leg_order"] for leg in payload["legs"]] == [1, 2]


def test_register_bet_validation_error_on_invalid_odds(client, seeded_events):
    event = seeded_events["S1"]

    response = client.post("/api/v1/bets", json=_bet_payload(event.id, legs=[_leg(event.id, odds_taken=0.5)]))

    assert response.status_code == 422


def test_register_simple_bet_with_two_legs_is_rejected(client, db_session, seeded_events):
    e1, e2 = seeded_events["S1"], seeded_events["S2"]

    response = client.post(
        "/api/v1/bets",
        json=_bet_payload(e1.id, bet_type="simple", legs=[_leg(e1.id), _leg(e2.id, selection="away")]),
    )

    assert response.status_code == 422


def test_register_compound_bet_with_duplicate_event_is_rejected(client, db_session, seeded_events):
    event = seeded_events["S1"]

    response = client.post(
        "/api/v1/bets",
        json=_bet_payload(
            event.id,
            bet_type="compound",
            legs=[_leg(event.id, selection="home"), _leg(event.id, selection="away")],
        ),
    )

    assert response.status_code == 422


def test_register_bet_with_nonexistent_recommendation_is_rejected(client, seeded_events):
    event = seeded_events["S1"]

    response = client.post("/api/v1/bets", json=_bet_payload(event.id, recommendation_id=999999))

    assert response.status_code == 422


def test_register_bet_with_duplicate_recommendation_returns_conflict(client, db_session, seeded_events):
    event = seeded_events["S1"]
    recommendation = Recommendation(
        strategy_name="value_bet_v1",
        strategy_params={},
        bet_type="simple",
        bankroll_at_recommendation=1000.0,
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(recommendation)
    db_session.commit()

    first = client.post("/api/v1/bets", json=_bet_payload(event.id, recommendation_id=recommendation.id))
    assert first.status_code == 201

    second = client.post("/api/v1/bets", json=_bet_payload(event.id, recommendation_id=recommendation.id))

    assert second.status_code == 409


def test_register_trial_bet_does_not_touch_real_bankroll(client, db_session, seeded_events):
    event = seeded_events["S1"]

    response = client.post("/api/v1/bets", json=_bet_payload(event.id, mode="trial"))

    assert response.status_code == 201
    assert response.json()["mode"] == "trial"
    assert db_session.query(BankrollTransaction).count() == 0

    status_resp = client.get("/api/v1/bankroll/status")
    assert status_resp.json()["current_balance"] == 1000.0


def test_list_bets_returns_persisted_bets(client, db_session, seeded_events):
    event = seeded_events["S1"]
    client.post("/api/v1/bets", json=_bet_payload(event.id))

    response = client.get("/api/v1/bets")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["legs"][0]["event_id"] == event.id


def test_list_bets_filtered_by_status(client, db_session, seeded_events):
    event = seeded_events["S1"]
    create_resp = client.post("/api/v1/bets", json=_bet_payload(event.id))
    bet_id = create_resp.json()["id"]
    client.post(f"/api/v1/bets/{bet_id}/settle", json={"leg_results": [{"leg_order": 1, "result": "won"}]})

    pending = client.get("/api/v1/bets", params={"status": "pending"}).json()
    settled = client.get("/api/v1/bets", params={"status": "settled"}).json()

    assert pending == []
    assert len(settled) == 1
    assert settled[0]["id"] == bet_id


def test_settle_bet_won_credits_payout_to_bankroll(client, db_session, seeded_events):
    event = seeded_events["S1"]
    create_resp = client.post("/api/v1/bets", json=_bet_payload(event.id, legs=[_leg(event.id, odds_taken=2.0)], stake=50.0))
    bet_id = create_resp.json()["id"]

    response = client.post(f"/api/v1/bets/{bet_id}/settle", json={"leg_results": [{"leg_order": 1, "result": "won"}]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "settled"
    assert payload["settlement"]["status"] == "won"
    assert payload["settlement"]["payout"] == 100.0
    assert payload["settlement"]["profit_loss"] == 50.0

    # -50 al registrar (950). Al ganar, el endpoint acredita el payout
    # completo (stake * odds), no solo la ganancia neta, porque el stake ya
    # fue descontado al registrar: 50*2.0 = 100 => 950 + 100 = 1050.
    status_resp = client.get("/api/v1/bankroll/status")
    assert status_resp.json()["current_balance"] == 1050.0

    transactions = db_session.query(BankrollTransaction).order_by(BankrollTransaction.id).all()
    assert len(transactions) == 2
    assert transactions[1].reason == "bet_won"
    assert float(transactions[1].amount) == 100.0


def test_settle_bet_lost_does_not_return_stake(client, seeded_events):
    event = seeded_events["S1"]
    create_resp = client.post("/api/v1/bets", json=_bet_payload(event.id, stake=50.0))
    bet_id = create_resp.json()["id"]

    response = client.post(f"/api/v1/bets/{bet_id}/settle", json={"leg_results": [{"leg_order": 1, "result": "lost"}]})

    assert response.json()["settlement"]["status"] == "lost"
    status_resp = client.get("/api/v1/bankroll/status")
    assert status_resp.json()["current_balance"] == 950.0


def test_settle_bet_void_returns_stake(client, seeded_events):
    event = seeded_events["S1"]
    create_resp = client.post("/api/v1/bets", json=_bet_payload(event.id, stake=50.0))
    bet_id = create_resp.json()["id"]

    client.post(f"/api/v1/bets/{bet_id}/settle", json={"leg_results": [{"leg_order": 1, "result": "void"}]})

    status_resp = client.get("/api/v1/bankroll/status")
    assert status_resp.json()["current_balance"] == 1000.0


def test_settle_compound_manual_review_does_not_touch_bankroll_and_keeps_bet_pending(
    client, db_session, seeded_events
):
    e1, e2 = seeded_events["S1"], seeded_events["S2"]
    create_resp = client.post(
        "/api/v1/bets",
        json=_bet_payload(
            e1.id,
            bet_type="compound",
            stake=20.0,
            legs=[_leg(e1.id, odds_taken=1.8), _leg(e2.id, odds_taken=1.7, selection="away")],
        ),
    )
    bet_id = create_resp.json()["id"]

    response = client.post(
        f"/api/v1/bets/{bet_id}/settle",
        json={"leg_results": [{"leg_order": 1, "result": "won"}, {"leg_order": 2, "result": "void"}]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["settlement"]["status"] == "manual_review"
    assert payload["settlement"]["payout"] is None
    assert payload["settlement"]["profit_loss"] is None

    status_resp = client.get("/api/v1/bankroll/status")
    assert status_resp.json()["current_balance"] == 980.0  # solo se descontó el stake al registrar


def test_bet_won_full_flow_balance_1000_950_1050(client, seeded_events):
    """Caso explicito de la regla de negocio:

    balance inicial = 1000, stake = 50, odds = 2.0
    registro -> 950 (se descuenta el stake)
    won -> 1050 (se acredita el payout completo: 50 * 2.0 = 100)
    """
    event = seeded_events["S1"]

    create_resp = client.post(
        "/api/v1/bets", json=_bet_payload(event.id, legs=[_leg(event.id, odds_taken=2.0)], stake=50.0)
    )
    assert create_resp.status_code == 201
    bet_id = create_resp.json()["id"]

    balance_after_register = client.get("/api/v1/bankroll/status").json()["current_balance"]
    assert balance_after_register == 950.0

    settle_resp = client.post(f"/api/v1/bets/{bet_id}/settle", json={"leg_results": [{"leg_order": 1, "result": "won"}]})
    assert settle_resp.status_code == 200

    balance_after_won = client.get("/api/v1/bankroll/status").json()["current_balance"]
    assert balance_after_won == 1050.0


def test_settle_bet_already_settled_returns_conflict(client, seeded_events):
    event = seeded_events["S1"]
    create_resp = client.post("/api/v1/bets", json=_bet_payload(event.id))
    bet_id = create_resp.json()["id"]
    client.post(f"/api/v1/bets/{bet_id}/settle", json={"leg_results": [{"leg_order": 1, "result": "won"}]})

    response = client.post(f"/api/v1/bets/{bet_id}/settle", json={"leg_results": [{"leg_order": 1, "result": "lost"}]})

    assert response.status_code == 409


def test_settle_bet_not_found_returns_404(client):
    response = client.post("/api/v1/bets/999999/settle", json={"leg_results": [{"leg_order": 1, "result": "won"}]})

    assert response.status_code == 404


def test_settle_bet_with_mismatched_leg_results_returns_422(client, seeded_events):
    event = seeded_events["S1"]
    create_resp = client.post("/api/v1/bets", json=_bet_payload(event.id))
    bet_id = create_resp.json()["id"]

    response = client.post(
        f"/api/v1/bets/{bet_id}/settle",
        json={"leg_results": [{"leg_order": 1, "result": "won"}, {"leg_order": 2, "result": "won"}]},
    )

    assert response.status_code == 422
