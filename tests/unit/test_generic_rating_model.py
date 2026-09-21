from datetime import datetime

import pytest

from app.domain.models import EventStatus, MatchEvent
from app.features.feature_builder import build_features
from app.models.generic_rating_model import GenericRatingModel


def _event(
    external_id: str,
    home: str,
    away: str,
    start_time: datetime,
    status: EventStatus = EventStatus.FINISHED,
    result: str | None = None,
    sport: str = "soccer",
) -> MatchEvent:
    return MatchEvent(
        external_id=external_id,
        sport=sport,
        league="Test League",
        competitor_home=home,
        competitor_away=away,
        start_time=start_time,
        status=status,
        source="test",
        result=result,
    )


def test_stronger_team_gets_higher_probability_without_draw():
    history = [
        _event("H1", "Strong", "Weak", datetime(2026, 1, 1), result="home_win"),
        _event("H2", "Strong", "Weak", datetime(2026, 1, 8), result="home_win"),
        _event("H3", "Strong", "Weak", datetime(2026, 1, 15), result="home_win"),
    ]
    target = _event("T1", "Strong", "Weak", datetime(2026, 1, 22), status=EventStatus.SCHEDULED)

    features = build_features(target, history)
    assert features["allows_draw"] is False

    model = GenericRatingModel()
    estimates = model.estimate(target, "match_winner", features)
    by_selection = {e.selection: e.probability for e in estimates}

    assert by_selection["home"] > by_selection["away"]
    assert by_selection["home"] + by_selection["away"] == pytest.approx(1.0)


def test_draw_probability_is_reserved_when_sport_allows_draw():
    history = [
        _event("H1", "A", "B", datetime(2026, 1, 1), result="draw"),
    ]
    target = _event("T1", "A", "B", datetime(2026, 1, 8), status=EventStatus.SCHEDULED)

    features = build_features(target, history)
    assert features["allows_draw"] is True

    model = GenericRatingModel(draw_probability=0.3)
    estimates = model.estimate(target, "1x2", features)
    by_selection = {e.selection: e.probability for e in estimates}

    assert by_selection["draw"] == pytest.approx(0.3)
    assert sum(by_selection.values()) == pytest.approx(1.0)


def test_only_uses_history_strictly_before_target_event():
    history = [
        _event("H1", "A", "B", datetime(2026, 1, 1), result="home_win"),
        _event("FUTURE", "A", "B", datetime(2026, 2, 1), result="away_win"),
    ]
    target = _event("T1", "A", "B", datetime(2026, 1, 15), status=EventStatus.SCHEDULED)

    features = build_features(target, history)
    model = GenericRatingModel()
    estimates = model.estimate(target, "match_winner", features)
    by_selection = {e.selection: e.probability for e in estimates}

    # Solo deberia contar H1 (A gano), no el evento futuro donde A pierde.
    assert by_selection["home"] > by_selection["away"]
