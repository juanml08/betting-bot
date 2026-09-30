import math
import random

import pytest

from app.db.models import Opportunity
from app.decisions.decision_engine import DecisionEngine
from app.valuation.growth import expected_value, kelly_full, log_growth


def opp(id, p, odds, *, event_id=None, status="candidate", stored_ev=0.0):
    # expected_value persistido es deliberadamente arbitrario: el Engine
    # debe recalcular desde estimated_probability y odds_value.
    return Opportunity(
        id=id,
        event_id=event_id if event_id is not None else id,
        market_type="1x2",
        selection="home",
        bookmaker="b",
        odds_value=odds,
        estimated_probability=p,
        implied_probability=0.5,
        edge=0.0,
        expected_value=stored_ev,
        kelly_fraction_suggested=0.0,
        suggested_stake=0.0,
        status=status,
    )


engine = DecisionEngine()


# ---------- matematica ----------


def test_log_growth_reference_values():
    assert log_growth(0.75, 2.0) == pytest.approx(0.13081, abs=1e-5)
    # C1: compound 0.75@2.0 + 0.51@2.0
    assert log_growth(0.75 * 0.51, 4.0) == pytest.approx(0.04263, abs=1e-5)


@pytest.mark.parametrize("p,odds", [(0.75, 2.0), (0.51, 2.0), (0.4, 3.0), (0.55, 2.0), (0.1, 12.0), (0.9, 1.2)])
def test_growth_positive_when_ev_positive(p, odds):
    assert expected_value(p, odds) > 0
    assert log_growth(p, odds) > 0


def test_growth_is_zero_at_zero_ev():
    assert log_growth(0.5, 2.0) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("p,odds", [(0.3, 2.0), (0.1, 5.0), (0.9, 1.05)])
def test_ev_le_zero_never_competes_even_if_formula_is_positive(p, odds):
    # La formula G* solo es el maximo de crecimiento cuando EV > 0 (f* > 0);
    # con EV < 0 la expresion es positiva pero carece de sentido. El Engine
    # usa EV > 0 como puerta de entrada, por eso estas no compiten.
    assert expected_value(p, odds) < 0
    assert engine.decide([opp(1, p, odds)], "real").bet_type == "no_bet"


def test_kelly_full_formula():
    assert kelly_full(0.75, 2.0) == pytest.approx(0.5)
    assert kelly_full(0.6, 1.8) == pytest.approx((0.6 * 1.8 - 1) / 0.8)


def test_compound_metrics_two_and_three_legs():
    r = engine.decide([opp(1, 0.6, 1.8), opp(2, 0.65, 1.7)], "trial")
    c = r.decision_metadata["compound"]
    p, o = 0.6 * 0.65, 1.8 * 1.7
    assert c["number_of_legs"] == 2
    assert c["probability"] == pytest.approx(p)
    assert c["odds"] == pytest.approx(o)
    assert c["expected_value"] == pytest.approx(p * o - 1)
    assert c["kelly_full"] == pytest.approx((p * o - 1) / (o - 1))
    assert c["growth"] == pytest.approx(log_growth(p, o))
    assert c["probability_method"] == "independence_assumption"

    r3 = engine.decide([opp(1, 0.55, 2.0), opp(2, 0.55, 2.0), opp(3, 0.55, 2.0)], "trial")
    c3 = r3.decision_metadata["compound"]
    p3, o3 = 0.55**3, 8.0
    assert c3["number_of_legs"] == 3
    assert c3["probability"] == pytest.approx(p3)
    assert c3["odds"] == pytest.approx(o3)
    assert c3["expected_value"] == pytest.approx(p3 * o3 - 1)
    assert c3["kelly_full"] == pytest.approx((p3 * o3 - 1) / (o3 - 1))
    assert c3["growth"] == pytest.approx(log_growth(p3, o3))


# ---------- modo / ids / status ----------


def test_mode_is_required_and_validated():
    with pytest.raises(ValueError):
        engine.decide([opp(1, 0.6, 2.0)], "paper")
    with pytest.raises(TypeError):
        engine.decide([opp(1, 0.6, 2.0)])  # type: ignore[call-arg]


def test_mode_is_echoed():
    assert engine.decide([], "trial").mode == "trial"


def test_repeated_or_missing_ids_rejected():
    with pytest.raises(ValueError):
        engine.decide([opp(1, 0.6, 2.0), opp(1, 0.7, 2.0)], "real")
    with pytest.raises(ValueError):
        engine.decide([opp(None, 0.6, 2.0)], "real")


def test_max_legs_must_be_positive():
    with pytest.raises(ValueError):
        DecisionEngine(max_legs=0)


def test_only_candidate_status_is_eligible():
    r = engine.decide([opp(1, 0.9, 2.0, status="selected"), opp(2, 0.6, 2.0)], "real")
    assert r.bet_type == "simple"
    assert r.opportunity_ids == [2]
    assert r.discarded_opportunity_ids == []
    assert r.decision_metadata["counts"]["candidate"] == 1


def test_stored_ev_is_ignored():
    # p*o-1 = 0.2 aunque el EV persistido diga otra cosa
    r = engine.decide([opp(1, 0.6, 2.0, stored_ev=-5.0)], "real")
    assert r.bet_type == "simple"
    assert r.decision_metadata["simple"]["expected_value"] == pytest.approx(0.2)


# ---------- NO_BET ----------


def test_no_candidates_is_no_bet():
    r = engine.decide([], "real")
    assert r.bet_type == "no_bet"
    assert r.opportunity_ids == []
    assert "valor esperado positivo" in r.explanation
    assert r.decision_metadata["technical_limit"]["hit"] is False


def test_non_positive_ev_is_no_bet_and_zero_is_not_positive():
    # EV: -0.2, exactamente 0 (0.5*2-1), -0.1
    r = engine.decide([opp(1, 0.4, 2.0), opp(2, 0.5, 2.0), opp(3, 0.45, 2.0)], "real")
    assert r.bet_type == "no_bet"
    assert r.opportunity_ids == []
    assert r.discarded_opportunity_ids == [1, 2, 3]
    assert r.decision_metadata["counts"]["positive_value"] == 0


@pytest.mark.parametrize(
    "p,odds",
    [
        (0.0, 2.0),
        (-0.1, 2.0),
        (1.0, 2.0),
        (1.2, 2.0),
        (0.6, 1.0),
        (0.6, 0.9),
        (math.nan, 2.0),
        (0.6, math.nan),
        (math.inf, 2.0),
        (0.6, math.inf),
        (None, 2.0),
    ],
)
def test_invalid_opportunity_is_excluded_not_raised(p, odds):
    r = engine.decide([opp(1, p, odds)], "real")
    assert r.bet_type == "no_bet"
    assert r.decision_metadata["invalid_ids"] == [1]
    assert r.decision_metadata["counts"]["invalid"] == 1
    assert r.discarded_opportunity_ids == [1]


def test_invalid_does_not_block_valid_ones():
    r = engine.decide([opp(1, 1.0, 2.0), opp(2, 0.6, 2.0)], "real")
    assert r.bet_type == "simple"
    assert r.opportunity_ids == [2]
    assert r.decision_metadata["invalid_ids"] == [1]


# ---------- decision simple vs compound ----------


def test_c1_simple_wins_despite_higher_compound_ev():
    r = engine.decide([opp(1, 0.75, 2.0), opp(2, 0.51, 2.0)], "real")
    md = r.decision_metadata
    assert md["simple"]["expected_value"] == pytest.approx(0.50)
    assert md["compound"]["expected_value"] == pytest.approx(0.53, abs=1e-9)
    assert md["simple"]["growth"] > md["compound"]["growth"]
    assert r.bet_type == "simple"
    assert r.opportunity_ids == [1]
    assert r.discarded_opportunity_ids == [2]
    assert md["comparison"]["criterion"] == "log_growth_full_kelly"
    assert md["selected_reason"] == "simple_growth_higher"
    # el criterio anterior (EV) habria elegido la compound: solo diagnostico
    assert md["diagnostics"]["ev_only_selection"] == {"selected": "compound", "opportunity_ids": [1, 2]}


def test_c2_moderate_pair_prefers_compound():
    r = engine.decide([opp(1, 0.55, 2.0), opp(2, 0.55, 2.0)], "real")
    assert r.bet_type == "compound"
    assert r.opportunity_ids == [1, 2]
    assert "compound" in r.explanation and "independencia" in r.explanation


def test_c3_low_odds_pair_prefers_compound():
    r = engine.decide([opp(1, 0.78, 1.4), opp(2, 0.78, 1.4)], "real")
    assert r.bet_type == "compound"
    assert r.opportunity_ids == [1, 2]


def test_c4_three_moderate_is_deterministic():
    opps = [opp(i, 0.55, 2.0) for i in (1, 2, 3)]
    r = engine.decide(opps, "real")
    assert r.bet_type == "compound"
    assert r.opportunity_ids == [1, 2, 3]  # G* del triple > pares > simple
    assert r.decision_metadata["counts"]["combinations_evaluated"] == 4
    assert engine.decide(list(reversed(opps)), "real") == r


def test_compound_tie_prefers_fewer_legs_then_lowest_ids():
    # 4 identicas: el mejor G* es el triple; entre triples gana [1,2,3]
    r = engine.decide([opp(i, 0.55, 2.0) for i in range(4, 0, -1)], "real")
    assert r.opportunity_ids == [1, 2, 3]


def test_simple_tie_broken_by_lowest_id():
    r = engine.decide([opp(5, 0.6, 2.0, event_id=1), opp(3, 0.6, 2.0, event_id=1)], "real")
    assert r.opportunity_ids == [3]


def test_compound_never_repeats_event_id():
    r = engine.decide([opp(1, 0.6, 2.0, event_id=7), opp(2, 0.55, 2.2, event_id=7)], "real")
    assert r.bet_type == "simple"
    assert r.decision_metadata["compound"] is None
    assert r.decision_metadata["selected_reason"] == "no_compound_available"


def test_non_positive_leg_never_enters_compound():
    r = engine.decide([opp(1, 0.55, 2.0), opp(2, 0.55, 2.0), opp(3, 0.35, 2.0)], "real")
    assert r.opportunity_ids == [1, 2]
    assert r.discarded_opportunity_ids == [3]


def test_compound_has_at_most_three_legs():
    r = engine.decide([opp(i, 0.55, 2.0) for i in range(1, 7)], "real")
    assert len(r.opportunity_ids) <= 3


def test_metadata_shape():
    md = engine.decide([opp(1, 0.55, 2.0), opp(2, 0.55, 2.0)], "real").decision_metadata
    assert set(md) >= {
        "selected", "selected_reason", "comparison", "simple", "compound", "counts", "technical_limit", "diagnostics",
    }
    assert set(md["counts"]) == {
        "candidate", "invalid", "positive_value", "event_count", "legs_after_pruning", "combinations_evaluated",
    }
    assert set(md["simple"]) == {
        "opportunity_id", "event_id", "probability", "odds", "expected_value", "kelly_full", "growth",
    }
    assert set(md["technical_limit"]) == {"max_legs", "hit", "dropped"}
    assert md["technical_limit"]["max_legs"] == 100


# ---------- poda por dominancia ----------


def test_dominated_leg_is_pruned_within_event():
    r = engine.decide([opp(1, 0.60, 2.0, event_id=1), opp(2, 0.70, 2.0, event_id=1)], "real")
    assert r.decision_metadata["counts"]["legs_after_pruning"] == 1
    assert r.opportunity_ids == [2]
    assert r.discarded_opportunity_ids == [1]


def test_non_comparable_legs_are_both_kept():
    r = engine.decide([opp(1, 0.80, 1.4, event_id=1), opp(2, 0.40, 3.0, event_id=1)], "real")
    assert r.decision_metadata["counts"]["legs_after_pruning"] == 2


def test_identical_legs_in_different_events_are_kept():
    r = engine.decide([opp(1, 0.6, 2.0, event_id=1), opp(2, 0.6, 2.0, event_id=2)], "real")
    assert r.decision_metadata["counts"]["legs_after_pruning"] == 2


def test_exact_tie_within_event_keeps_lowest_id():
    r = engine.decide([opp(4, 0.6, 2.0, event_id=1), opp(2, 0.6, 2.0, event_id=1)], "real")
    assert r.decision_metadata["counts"]["legs_after_pruning"] == 1
    assert r.opportunity_ids == [2]


# ---------- limite tecnico ----------


def _spread(n):
    # n legs de eventos distintos con G* estrictamente decreciente por id
    return [opp(i, 0.70 - 0.01 * i, 2.0) for i in range(1, n + 1)]


def test_technical_limit_hit_drops_lowest_growth_legs():
    limited = DecisionEngine(max_legs=3)
    r = limited.decide(_spread(5), "real")
    tl = r.decision_metadata["technical_limit"]
    assert tl == {"max_legs": 3, "hit": True, "dropped": 2}
    assert r.decision_metadata["counts"]["legs_after_pruning"] == 5
    assert r.decision_metadata["counts"]["combinations_evaluated"] == 4  # C(3,2)+C(3,3)
    assert set(r.opportunity_ids) <= {1, 2, 3}
    assert limited.decide(list(reversed(_spread(5))), "real") == r


def test_below_limit_runs_full_search():
    r = DecisionEngine(max_legs=5).decide(_spread(5), "real")
    assert r.decision_metadata["technical_limit"] == {"max_legs": 5, "hit": False, "dropped": 0}
    assert r.decision_metadata["counts"]["combinations_evaluated"] == 10 + 10  # C(5,2)+C(5,3)


# ---------- determinismo ----------


def test_deterministic_for_sorted_reversed_and_shuffled_input():
    opps = [
        opp(1, 0.55, 2.0, event_id=1),
        opp(2, 0.60, 1.9, event_id=1),
        opp(3, 0.80, 1.4, event_id=2),
        opp(4, 0.40, 3.0, event_id=3),
        opp(5, 0.55, 2.0, event_id=4),
        opp(6, 0.55, 2.0, event_id=5),
        opp(7, 0.35, 2.0, event_id=6),
    ]
    baseline = engine.decide(opps, "real")
    assert engine.decide(list(reversed(opps)), "real") == baseline
    rng = random.Random(7)
    for _ in range(10):
        shuffled = opps[:]
        rng.shuffle(shuffled)
        assert engine.decide(shuffled, "real") == baseline


# ---------- integracion ----------


def test_result_is_consumable_by_recommendation_service_validation():
    from app.recommendations.recommendation_service import RecommendationService

    for opps in (
        [opp(1, 0.4, 2.0)],
        [opp(1, 0.55, 2.0), opp(2, 0.55, 2.0)],
        [opp(1, 0.75, 2.0), opp(2, 0.51, 2.0)],
    ):
        r = engine.decide(opps, "real")
        RecommendationService._validate_opportunity_ids(r.bet_type, r.opportunity_ids)
