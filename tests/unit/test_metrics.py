import pytest

from backtesting.engine import BacktestBetRecord, BacktestReport
from backtesting.metrics import compute_metrics


def _record(*, stake: float, odds_value: float, won: bool, probability: float, bankroll_after: float) -> BacktestBetRecord:
    profit = stake * (odds_value - 1.0) if won else -stake
    return BacktestBetRecord(
        event_external_id="E1",
        market_type="match_winner",
        selection="home",
        odds_value=odds_value,
        estimated_probability=probability,
        stake=stake,
        won=won,
        profit=profit,
        bankroll_after=bankroll_after,
    )


def test_metrics_on_empty_report():
    report = BacktestReport(initial_bankroll=1000.0, final_bankroll=1000.0, records=[])
    metrics = compute_metrics(report)
    assert metrics.num_bets == 0
    assert metrics.roi == 0.0


def test_metrics_compute_roi_and_win_rate():
    records = [
        _record(stake=100.0, odds_value=2.0, won=True, probability=0.55, bankroll_after=1100.0),
        _record(stake=100.0, odds_value=2.0, won=False, probability=0.55, bankroll_after=1000.0),
    ]
    report = BacktestReport(initial_bankroll=1000.0, final_bankroll=1000.0, records=records)
    metrics = compute_metrics(report)

    assert metrics.num_bets == 2
    assert metrics.total_staked == pytest.approx(200.0)
    assert metrics.total_profit == pytest.approx(0.0)
    assert metrics.roi == pytest.approx(0.0)
    assert metrics.win_rate == pytest.approx(0.5)
    assert metrics.brier_score == pytest.approx(((0.55 - 1.0) ** 2 + (0.55 - 0.0) ** 2) / 2)


def test_max_drawdown_reflects_worst_dip_from_peak():
    records = [
        _record(stake=100.0, odds_value=2.0, won=True, probability=0.55, bankroll_after=1100.0),
        _record(stake=200.0, odds_value=2.0, won=False, probability=0.55, bankroll_after=900.0),
    ]
    report = BacktestReport(initial_bankroll=1000.0, final_bankroll=900.0, records=records)
    metrics = compute_metrics(report)

    # Pico en 1100, cae a 900 -> drawdown de 200/1100
    assert metrics.max_drawdown == pytest.approx(200.0 / 1100.0)
