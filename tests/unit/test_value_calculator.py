from datetime import datetime

import pytest

from app.domain.models import OddsQuote, ProbabilityEstimate
from app.valuation.value_calculator import ValueCalculator


def _estimate(probability: float) -> ProbabilityEstimate:
    return ProbabilityEstimate(
        event_external_id="E1",
        market_type="match_winner",
        selection="home",
        model_name="test_model",
        model_version="0.0.1",
        probability=probability,
        computed_at=datetime(2026, 1, 1),
    )


def _quote(odds_value: float, selection: str = "home") -> OddsQuote:
    return OddsQuote(
        event_external_id="E1",
        market_type="match_winner",
        selection=selection,
        bookmaker="SampleBook",
        odds_value=odds_value,
        captured_at=datetime(2026, 1, 1),
    )


def test_positive_edge_when_estimate_beats_market():
    # Cuota de 2.5 implica ~40%; si estimamos 55%, deberia haber edge positivo.
    calculator = ValueCalculator()
    market_quotes = [_quote(2.5, "home"), _quote(2.5, "away")]
    opportunity = calculator.calculate(_estimate(0.55), market_quotes[0], market_quotes)

    assert opportunity.implied_probability == pytest.approx(0.5)
    assert opportunity.edge == pytest.approx(0.05)
    assert opportunity.expected_value > 0
    assert opportunity.kelly_fraction_suggested > 0


def test_negative_edge_when_market_beats_estimate():
    calculator = ValueCalculator()
    market_quotes = [_quote(2.5, "home"), _quote(2.5, "away")]
    opportunity = calculator.calculate(_estimate(0.3), market_quotes[0], market_quotes)

    assert opportunity.edge < 0
    assert opportunity.expected_value < 0
    assert opportunity.kelly_fraction_suggested == 0.0
