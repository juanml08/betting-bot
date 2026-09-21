from datetime import datetime

import pytest

from app.domain.models import OddsQuote
from app.odds.implied_probability import fair_implied_probability, overround, raw_implied_probability


def _quote(selection: str, odds_value: float) -> OddsQuote:
    return OddsQuote(
        event_external_id="E1",
        market_type="match_winner",
        selection=selection,
        bookmaker="SampleBook",
        odds_value=odds_value,
        captured_at=datetime(2026, 1, 1),
    )


def test_raw_implied_probability():
    assert raw_implied_probability(2.0) == pytest.approx(0.5)


def test_raw_implied_probability_rejects_invalid_odds():
    with pytest.raises(ValueError):
        raw_implied_probability(1.0)


def test_overround_reflects_bookmaker_margin():
    quotes = [_quote("home", 1.9), _quote("away", 2.1)]
    margin = overround(quotes)
    assert margin > 1.0


def test_fair_implied_probability_removes_margin():
    quotes = [_quote("home", 1.9), _quote("away", 2.1)]
    fair_home = fair_implied_probability(quotes[0], quotes)
    fair_away = fair_implied_probability(quotes[1], quotes)
    assert fair_home + fair_away == pytest.approx(1.0)
