from datetime import date

from app.db.models import BankrollTransaction


def test_bankroll_status_with_no_transactions_equals_initial_bankroll(client):
    response = client.get("/api/v1/bankroll/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["initial_bankroll"] == 1000.0
    assert payload["current_balance"] == 1000.0


def test_bankroll_status_reflects_persisted_transactions(client, db_session):
    db_session.add(
        BankrollTransaction(
            occurred_on=date(2026, 1, 5),
            amount=-50.0,
            reason="bet_placed",
            balance_after=950.0,
        )
    )
    db_session.add(
        BankrollTransaction(
            occurred_on=date(2026, 1, 6),
            amount=100.0,
            reason="bet_won",
            balance_after=1050.0,
        )
    )
    db_session.commit()

    response = client.get("/api/v1/bankroll/status")

    assert response.status_code == 200
    assert response.json()["current_balance"] == 1050.0


def test_list_transactions_returns_persisted_data_ordered_by_date(client, db_session):
    db_session.add(
        BankrollTransaction(
            occurred_on=date(2026, 1, 10),
            amount=100.0,
            reason="bet_won",
            balance_after=1100.0,
        )
    )
    db_session.add(
        BankrollTransaction(
            occurred_on=date(2026, 1, 1),
            amount=-50.0,
            reason="bet_placed",
            balance_after=950.0,
        )
    )
    db_session.commit()

    response = client.get("/api/v1/bankroll/transactions")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert payload[0]["occurred_on"] == "2026-01-01"
    assert payload[1]["occurred_on"] == "2026-01-10"
