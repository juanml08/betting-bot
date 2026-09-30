from types import SimpleNamespace

import pytest

from app.settlements.result_resolver import resolve_leg_result


def _event(status="finished", result="home_win"):
    return SimpleNamespace(status=status, result=result, competitor_home="Team A", competitor_away="Team B")


def _leg(selection="home", market_type="1x2"):
    return SimpleNamespace(selection=selection, market_type=market_type)


def test_home_selection_home_result_won():
    assert resolve_leg_result(_event(result="home_win"), _leg("home")) == "won"


def test_away_selection_home_result_lost():
    assert resolve_leg_result(_event(result="home_win"), _leg("away")) == "lost"


def test_home_selection_away_result_lost():
    assert resolve_leg_result(_event(result="away_win"), _leg("home")) == "lost"


def test_1x2_draw_selection_draw_result_won():
    assert resolve_leg_result(_event(result="draw"), _leg("draw")) == "won"


def test_1x2_team_selection_draw_result_lost():
    assert resolve_leg_result(_event(result="draw"), _leg("home")) == "lost"
    assert resolve_leg_result(_event(result="draw"), _leg("Team A")) == "lost"


def test_match_winner_team_selection_draw_result_lost_not_void():
    leg = _leg("Team A", market_type="match_winner")
    assert resolve_leg_result(_event(result="draw"), leg) == "lost"


def test_match_winner_team_name_selection():
    assert resolve_leg_result(_event(result="away_win"), _leg("Team B", "match_winner")) == "won"
    assert resolve_leg_result(_event(result="away_win"), _leg("Team A", "match_winner")) == "lost"


@pytest.mark.parametrize("result", [None, "home_win"])
def test_cancelled_is_void_regardless_of_result(result):
    assert resolve_leg_result(_event("cancelled", result), _leg()) == "void"


def test_finished_without_result_unresolved():
    assert resolve_leg_result(_event("finished", None), _leg()) == "unresolved"


def test_finished_with_unknown_result_unresolved():
    assert resolve_leg_result(_event("finished", "abandoned"), _leg()) == "unresolved"


@pytest.mark.parametrize("status", ["scheduled", "live"])
def test_scheduled_and_live_unresolved_even_with_result(status):
    assert resolve_leg_result(_event(status, "home_win"), _leg()) == "unresolved"


def test_unknown_market_or_selection_unresolved():
    assert resolve_leg_result(_event(), _leg("home", "over_under_2_5")) == "unresolved"
    assert resolve_leg_result(_event(), _leg("nobody")) == "unresolved"
