from app.db.models import BankrollTransaction, Bet


def _bet_payload(event_id: int, **overrides) -> dict:
    payload = dict(
        event_id=event_id,
        market_type="1x2",
        selection="home",
        odds_taken=1.9,
        stake=50.0,
        opportunity_id=None,
        notes=None,
    )
    payload.update(overrides)
    return payload


def test_register_bet_persists_and_updates_bankroll(client, db_session, seeded_events):
    event = seeded_events["S1"]

    response = client.post("/api/v1/bets", json=_bet_payload(event.id))

    assert response.status_code == 201
    payload = response.json()
    assert payload["event_id"] == event.id
    assert payload["status"] == "pending"
    assert payload["stake"] == 50.0
    assert payload["bankroll_at_time"] == 1000.0  # initial_bankroll de test_settings

    persisted_bet = db_session.query(Bet).filter_by(id=payload["id"]).one()
    assert persisted_bet.status == "pending"
    assert float(persisted_bet.stake) == 50.0

    transactions = db_session.query(BankrollTransaction).all()
    assert len(transactions) == 1
    assert transactions[0].reason == "bet_placed"
    assert float(transactions[0].amount) == -50.0
    assert float(transactions[0].balance_after) == 950.0
    assert transactions[0].related_bet_id == persisted_bet.id


def test_register_bet_validation_error_on_invalid_odds(client, seeded_events):
    event = seeded_events["S1"]

    response = client.post("/api/v1/bets", json=_bet_payload(event.id, odds_taken=0.5))

    assert response.status_code == 422


def test_list_bets_returns_persisted_bets(client, db_session, seeded_events):
    event = seeded_events["S1"]
    client.post("/api/v1/bets", json=_bet_payload(event.id))

    response = client.get("/api/v1/bets")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["event_id"] == event.id


def test_list_bets_filtered_by_status(client, db_session, seeded_events):
    event = seeded_events["S1"]
    create_resp = client.post("/api/v1/bets", json=_bet_payload(event.id))
    bet_id = create_resp.json()["id"]
    client.post(f"/api/v1/bets/{bet_id}/settle", json={"status": "won"})

    pending = client.get("/api/v1/bets", params={"status": "pending"}).json()
    settled = client.get("/api/v1/bets", params={"status": "won"}).json()

    assert pending == []
    assert len(settled) == 1
    assert settled[0]["id"] == bet_id


def test_settle_bet_won_credits_payout_to_bankroll(client, db_session, seeded_events):
    event = seeded_events["S1"]
    create_resp = client.post("/api/v1/bets", json=_bet_payload(event.id, odds_taken=2.0, stake=50.0))
    bet_id = create_resp.json()["id"]

    response = client.post(f"/api/v1/bets/{bet_id}/settle", json={"status": "won"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "won"
    assert payload["settled_at"] is not None

    # -50 al registrar. Al ganar, el endpoint acredita (payout - stake) = solo
    # la ganancia neta, no el payout completo (ver app/api/v1/endpoints/bets.py):
    # 50*2.0 - 50 = 50 => 950 + 50 = 1000.
    status_resp = client.get("/api/v1/bankroll/status")
    assert status_resp.json()["current_balance"] == 1000.0

    transactions = db_session.query(BankrollTransaction).order_by(BankrollTransaction.id).all()
    assert len(transactions) == 2
    assert transactions[1].reason == "bet_won"
    assert float(transactions[1].amount) == 50.0


def test_settle_bet_lost_does_not_return_stake(client, seeded_events):
    event = seeded_events["S1"]
    create_resp = client.post("/api/v1/bets", json=_bet_payload(event.id, stake=50.0))
    bet_id = create_resp.json()["id"]

    client.post(f"/api/v1/bets/{bet_id}/settle", json={"status": "lost"})

    status_resp = client.get("/api/v1/bankroll/status")
    assert status_resp.json()["current_balance"] == 950.0


def test_settle_bet_void_returns_stake(client, seeded_events):
    event = seeded_events["S1"]
    create_resp = client.post("/api/v1/bets", json=_bet_payload(event.id, stake=50.0))
    bet_id = create_resp.json()["id"]

    client.post(f"/api/v1/bets/{bet_id}/settle", json={"status": "void"})

    status_resp = client.get("/api/v1/bankroll/status")
    assert status_resp.json()["current_balance"] == 1000.0


def test_settle_bet_already_settled_returns_conflict(client, seeded_events):
    event = seeded_events["S1"]
    create_resp = client.post("/api/v1/bets", json=_bet_payload(event.id))
    bet_id = create_resp.json()["id"]
    client.post(f"/api/v1/bets/{bet_id}/settle", json={"status": "won"})

    response = client.post(f"/api/v1/bets/{bet_id}/settle", json={"status": "lost"})

    assert response.status_code == 409


def test_settle_bet_not_found_returns_404(client):
    response = client.post("/api/v1/bets/999999/settle", json={"status": "won"})

    assert response.status_code == 404
