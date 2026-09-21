from datetime import date

import pytest

from app.domain.models import ValueOpportunity
from app.risk.bankroll import FractionalKellyRiskManager, RiskConfig
from app.risk.bankroll_manager import BankrollManager, BankrollMovement


def _opportunity(kelly_fraction_suggested: float) -> ValueOpportunity:
    return ValueOpportunity(
        event_external_id="E1",
        market_type="match_winner",
        selection="home",
        bookmaker="SampleBook",
        odds_value=2.0,
        estimated_probability=0.55,
        implied_probability=0.5,
        edge=0.05,
        expected_value=0.1,
        kelly_fraction_suggested=kelly_fraction_suggested,
    )


def test_fractional_kelly_scales_down_full_kelly():
    manager = FractionalKellyRiskManager(RiskConfig(kelly_fraction=0.25, max_stake_pct_per_bet=1.0))
    stake = manager.suggest_stake(_opportunity(0.2), current_bankroll=1000.0)
    assert stake == pytest.approx(0.25 * 0.2 * 1000.0)


def test_stake_is_capped_by_max_stake_pct():
    manager = FractionalKellyRiskManager(RiskConfig(kelly_fraction=1.0, max_stake_pct_per_bet=0.05))
    stake = manager.suggest_stake(_opportunity(0.5), current_bankroll=1000.0)
    assert stake == pytest.approx(0.05 * 1000.0)


def test_zero_bankroll_yields_zero_stake():
    manager = FractionalKellyRiskManager(RiskConfig(kelly_fraction=0.25, max_stake_pct_per_bet=0.05))
    assert manager.suggest_stake(_opportunity(0.2), current_bankroll=0.0) == 0.0


def test_bankroll_manager_tracks_balance_and_daily_exposure():
    movements = [
        BankrollMovement(occurred_on=date(2026, 1, 1), amount=-50.0),
        BankrollMovement(occurred_on=date(2026, 1, 1), amount=-30.0),
        BankrollMovement(occurred_on=date(2026, 1, 2), amount=20.0),
    ]
    manager = BankrollManager(initial_bankroll=1000.0, movements=movements)

    assert manager.current_balance == pytest.approx(940.0)
    assert manager.exposure_on(date(2026, 1, 1)) == pytest.approx(80.0)
    assert manager.exposure_on(date(2026, 1, 3)) == 0.0

    remaining = manager.remaining_daily_capacity(date(2026, 1, 1), max_daily_exposure_pct=0.10)
    assert remaining == pytest.approx(max(940.0 * 0.10 - 80.0, 0.0))
