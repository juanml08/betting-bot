from app.db.models import BacktestRun


def test_run_backtest_returns_metrics_and_persists_run(client_permissive_backtest, db_session):
    response = client_permissive_backtest.post(
        "/api/v1/backtest/run",
        json={"date_from": "2026-01-01", "date_to": "2026-01-31"},
    )

    assert response.status_code == 200
    payload = response.json()
    # Solo hay eventos finalizados en enero en los fixtures (ver tests/fixtures).
    assert payload["num_bets"] > 0
    assert 0.0 <= payload["win_rate"] <= 1.0
    assert payload["max_drawdown"] >= 0.0
    assert payload["date_from"] == "2026-01-01"
    assert payload["date_to"] == "2026-01-31"

    persisted = db_session.query(BacktestRun).all()
    assert len(persisted) == 1
    run = persisted[0]
    assert run.num_bets == payload["num_bets"]
    assert float(run.roi) == payload["roi"]
    assert run.date_from.isoformat() == "2026-01-01"
    assert run.date_to.isoformat() == "2026-01-31"


def test_run_backtest_with_no_finished_events_in_range_returns_zero_bets(client_permissive_backtest, db_session):
    response = client_permissive_backtest.post(
        "/api/v1/backtest/run",
        json={"date_from": "2020-01-01", "date_to": "2020-01-31"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["num_bets"] == 0

    persisted = db_session.query(BacktestRun).all()
    assert len(persisted) == 1
