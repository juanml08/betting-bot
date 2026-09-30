from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import OperationalError

from app.db.models import BankrollTransaction, Bet, BetLeg, Event, Opportunity, Settlement
from app.db.repositories.bet_repository import BetRepository
from app.db.repositories.recommendation_repository import RecommendationRepository
from app.db.repositories.settlement_repository import SettlementRepository
from app.decisions.decision_engine import DecisionEngine
from app.recommendations.recommendation_service import RecommendationService
from app.risk.bankroll import FractionalKellyRiskManager, RiskConfig
from app.settlements.settlement_service import SettlementService
from app.trials.trial_executor import (
    RecommendationNotExecutableError,
    RecommendationNotFoundError,
    TrialExecutor,
)

PLACED_AT = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
START = datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc)
BANKROLL = 1000.0
KELLY_FRACTION = 0.25
MAX_PCT = 0.05


@pytest.fixture()
def executor(db_session) -> TrialExecutor:
    risk = FractionalKellyRiskManager(RiskConfig(kelly_fraction=KELLY_FRACTION, max_stake_pct_per_bet=MAX_PCT))
    return TrialExecutor(db_session, risk)


def _event(db_session, n=1, *, status="scheduled", start_time=START) -> Event:
    event = Event(
        external_id=f"EV{n}-{status}",
        sport="soccer",
        league="L",
        competitor_home="A",
        competitor_away="B",
        start_time=start_time,
        status=status,
        source="sample",
    )
    db_session.add(event)
    db_session.flush()
    return event


def _opportunity(db_session, event, *, p=0.6, odds=2.0, kelly=0.2, status="candidate", selection="home"):
    o = Opportunity(
        event_id=event.id,
        market_type="1x2",
        selection=selection,
        bookmaker="SampleBook",
        odds_value=odds,
        estimated_probability=p,
        implied_probability=1 / odds,
        edge=p - 1 / odds,
        expected_value=p * odds - 1,
        kelly_fraction_suggested=kelly,
        suggested_stake=10.0,
        status=status,
        created_at=PLACED_AT,
    )
    db_session.add(o)
    db_session.flush()
    return o


def _recommendation(db_session, opportunity_ids, *, bet_type, mode="trial", metadata=None):
    rec = RecommendationService(RecommendationRepository(db_session)).create_recommendation(
        mode=mode,
        strategy_name="test",
        strategy_params={},
        bet_type=bet_type,
        bankroll_at_recommendation=BANKROLL,
        opportunity_ids=opportunity_ids,
        generated_at=PLACED_AT,
        decision_metadata=metadata,
    )
    db_session.flush()
    return rec


def _simple_rec(db_session, **opp_kwargs):
    opp = _opportunity(db_session, _event(db_session), **opp_kwargs)
    return _recommendation(db_session, [opp.id], bet_type="simple"), opp


def _compound_rec(db_session):
    """Compound real: la decide DecisionEngine y se persiste su metadata."""
    opps = [_opportunity(db_session, _event(db_session, n)) for n in (1, 2)]
    decision = DecisionEngine().decide(opps, "trial")
    assert decision.bet_type == "compound"
    rec = _recommendation(
        db_session,
        decision.opportunity_ids,
        bet_type=decision.bet_type,
        metadata=decision.decision_metadata,
    )
    return rec, opps, decision


# --- ejecucion valida -------------------------------------------------------


def test_simple_creates_pending_trial_bet_with_frozen_leg(db_session, executor):
    rec, opp = _simple_rec(db_session, odds=2.5, p=0.5, kelly=0.2)

    result = executor.execute(rec.id, PLACED_AT)

    bet = result.bet
    assert result.created is True
    assert (bet.mode, bet.status, bet.bet_type) == ("trial", "pending", "simple")
    assert bet.recommendation_id == rec.id
    assert float(bet.bankroll_at_time) == BANKROLL
    assert bet.placed_at == PLACED_AT
    assert len(bet.legs) == 1
    leg = bet.legs[0]
    assert (leg.event_id, leg.market_type, leg.selection, leg.bookmaker) == (
        opp.event_id,
        "1x2",
        "home",
        "SampleBook",
    )
    assert float(leg.odds_taken) == 2.5
    assert leg.result == "pending"


def test_simple_stake_comes_from_risk_manager_with_cap(db_session, executor):
    # 0.2 * 0.25 = 0.05 -> 50.00 (igual al tope)
    rec, _ = _simple_rec(db_session, kelly=0.2)
    assert float(executor.execute(rec.id, PLACED_AT).bet.stake) == 50.0


def test_simple_stake_is_capped_by_max_stake_pct(db_session, executor):
    # 0.8 * 0.25 = 0.2 > 0.05 -> 50.00
    rec, _ = _simple_rec(db_session, kelly=0.8)
    assert float(executor.execute(rec.id, PLACED_AT).bet.stake) == 50.0


def test_simple_stake_below_cap_uses_fractional_kelly(db_session, executor):
    # 0.08 * 0.25 = 0.02 -> 20.00
    rec, _ = _simple_rec(db_session, kelly=0.08)
    assert float(executor.execute(rec.id, PLACED_AT).bet.stake) == 20.0


def test_compound_uses_decision_engine_metadata_for_stake(db_session, executor):
    rec, opps, decision = _compound_rec(db_session)
    kelly_full = decision.decision_metadata["compound"]["kelly_full"]

    result = executor.execute(rec.id, PLACED_AT)

    bet = result.bet
    assert (bet.bet_type, bet.mode, bet.status) == ("compound", "trial", "pending")
    assert [leg.leg_order for leg in bet.legs] == [1, 2]
    assert [leg.event_id for leg in bet.legs] == [o.event_id for o in opps]
    assert all(float(leg.odds_taken) == 2.0 for leg in bet.legs)
    expected = round(min(kelly_full * KELLY_FRACTION, MAX_PCT) * BANKROLL, 2)
    assert float(bet.stake) == expected
    assert 0 < expected < MAX_PCT * BANKROLL  # ejerce la fraccion, no el tope


def test_compound_metadata_missing_is_not_executable(db_session, executor):
    opps = [_opportunity(db_session, _event(db_session, n)) for n in (1, 2)]
    rec = _recommendation(db_session, [o.id for o in opps], bet_type="compound", metadata=None)
    with pytest.raises(RecommendationNotExecutableError, match="decision_metadata"):
        executor.execute(rec.id, PLACED_AT)
    assert db_session.query(Bet).count() == 0


def test_compound_metadata_mismatching_opportunities_is_not_executable(db_session, executor):
    rec, _, _ = _compound_rec(db_session)
    rec.decision_metadata = {"compound": {**rec.decision_metadata["compound"], "opportunity_ids": [999, 1000]}}
    db_session.flush()
    with pytest.raises(RecommendationNotExecutableError, match="no coincide"):
        executor.execute(rec.id, PLACED_AT)


def test_execution_is_deterministic(db_session, executor):
    rec_a, _, _ = _compound_rec(db_session)
    stake_a = float(executor.execute(rec_a.id, PLACED_AT).bet.stake)
    # Segunda recomendacion identica sobre otros eventos: mismo stake.
    opps = [_opportunity(db_session, _event(db_session, n)) for n in (3, 4)]
    decision = DecisionEngine().decide(opps, "trial")
    rec_b = _recommendation(
        db_session, decision.opportunity_ids, bet_type="compound", metadata=decision.decision_metadata
    )
    assert float(executor.execute(rec_b.id, PLACED_AT).bet.stake) == stake_a


# --- no_bet y errores de negocio -------------------------------------------


def test_no_bet_does_not_execute(db_session, executor):
    rec = _recommendation(db_session, [], bet_type="no_bet")
    result = executor.execute(rec.id, PLACED_AT)
    assert (result.bet, result.created, result.reason) == (None, False, "no_bet")
    assert db_session.query(Bet).count() == 0
    assert db_session.query(BetLeg).count() == 0
    assert db_session.query(BankrollTransaction).count() == 0


def test_missing_recommendation(executor):
    with pytest.raises(RecommendationNotFoundError):
        executor.execute(12345, PLACED_AT)


def test_real_recommendation_is_not_executable(db_session, executor):
    opp = _opportunity(db_session, _event(db_session))
    rec = _recommendation(db_session, [opp.id], bet_type="simple", mode="real")
    with pytest.raises(RecommendationNotExecutableError, match="trial"):
        executor.execute(rec.id, PLACED_AT)
    assert db_session.query(Bet).count() == 0


def test_missing_opportunity_is_not_executable(db_session, db_engine, executor):
    rec, opp = _simple_rec(db_session)
    db_session.commit()
    # Simula un dato huerfano: SQLite aplica FKs, se desactivan solo para borrar.
    raw = db_engine.raw_connection()
    try:
        raw.execute("PRAGMA foreign_keys=OFF")
        raw.execute("DELETE FROM opportunities WHERE id = ?", (opp.id,))
        raw.commit()
    finally:
        raw.execute("PRAGMA foreign_keys=ON")
        raw.close()
    db_session.expire_all()
    with pytest.raises(RecommendationNotExecutableError, match="no existe"):
        executor.execute(rec.id, PLACED_AT)


def test_recommendation_without_legs_is_not_executable(db_session, executor):
    from app.db.models import Recommendation

    rec = Recommendation(
        mode="trial",
        strategy_name="t",
        strategy_params={},
        bet_type="simple",
        bankroll_at_recommendation=BANKROLL,
        generated_at=PLACED_AT,
    )
    db_session.add(rec)
    db_session.flush()
    with pytest.raises(RecommendationNotExecutableError, match="inconsistente"):
        executor.execute(rec.id, PLACED_AT)


@pytest.mark.parametrize("status", ["settled", "cancelled", "expired", "executed"])
def test_opportunity_with_non_candidate_status_is_not_executable(db_session, executor, status):
    rec, _ = _simple_rec(db_session, status=status)
    with pytest.raises(RecommendationNotExecutableError, match="Opportunity"):
        executor.execute(rec.id, PLACED_AT)
    assert db_session.query(Bet).count() == 0


@pytest.mark.parametrize("status", ["live", "finished", "cancelled"])
def test_event_with_incompatible_status_is_not_executable(db_session, executor, status):
    event = _event(db_session, status=status)
    opp = _opportunity(db_session, event)
    rec = _recommendation(db_session, [opp.id], bet_type="simple")
    with pytest.raises(RecommendationNotExecutableError, match="Evento"):
        executor.execute(rec.id, PLACED_AT)
    assert db_session.query(Bet).count() == 0


@pytest.mark.parametrize("delta_seconds", [0, -60])
def test_event_already_started_is_not_executable(db_session, executor, delta_seconds):
    from datetime import timedelta

    event = _event(db_session, start_time=PLACED_AT + timedelta(seconds=delta_seconds))
    opp = _opportunity(db_session, event)
    rec = _recommendation(db_session, [opp.id], bet_type="simple")
    with pytest.raises(RecommendationNotExecutableError, match="ya comenzo"):
        executor.execute(rec.id, PLACED_AT)


def test_one_invalid_leg_prevents_whole_compound_and_persists_nothing(db_session, executor):
    rec, opps, _ = _compound_rec(db_session)
    opps[1].event.status = "live"
    db_session.flush()
    with pytest.raises(RecommendationNotExecutableError):
        executor.execute(rec.id, PLACED_AT)
    assert db_session.query(Bet).count() == 0
    assert db_session.query(BetLeg).count() == 0


def test_zero_stake_is_not_executable(db_session, executor):
    rec, _ = _simple_rec(db_session, kelly=0.0)
    with pytest.raises(RecommendationNotExecutableError, match="stake"):
        executor.execute(rec.id, PLACED_AT)
    assert db_session.query(Bet).count() == 0


# --- idempotencia -----------------------------------------------------------


def test_repeated_execution_returns_existing_bet(db_session, executor):
    rec, _ = _simple_rec(db_session)
    first = executor.execute(rec.id, PLACED_AT)
    second = executor.execute(rec.id, PLACED_AT)
    assert first.created is True and second.created is False
    assert second.bet.id == first.bet.id
    assert db_session.query(Bet).count() == 1
    assert db_session.query(BetLeg).count() == 1


def test_repeated_execution_after_event_started_still_returns_existing(db_session, executor):
    from datetime import timedelta

    rec, _ = _simple_rec(db_session)
    first = executor.execute(rec.id, PLACED_AT)
    later = executor.execute(rec.id, START + timedelta(hours=1))
    assert later.created is False and later.bet.id == first.bet.id


def test_concurrent_race_is_resolved_by_unique_constraint(db_session, executor, monkeypatch):
    """Otro proceso crea el Bet entre la consulta previa y el insert: la
    constraint UNIQUE lo detecta, el SAVEPOINT se descarta y se devuelve el
    Bet ganador sin destruir la transaccion externa."""
    rec, _ = _simple_rec(db_session)
    winner = BetRepository(db_session).create(
        bet_type="simple",
        mode="trial",
        stake=11.0,
        bankroll_at_time=BANKROLL,
        placed_at=PLACED_AT,
        legs=[
            dict(event_id=rec.legs[0].opportunity.event_id, market_type="1x2", selection="home",
                 bookmaker="SampleBook", odds_taken=2.0)
        ],
        recommendation_id=rec.id,
    )
    db_session.commit()

    real_lookup = BetRepository.get_by_recommendation
    calls = {"n": 0}

    def stale_first_lookup(self, recommendation_id):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_lookup(self, recommendation_id)

    monkeypatch.setattr(BetRepository, "get_by_recommendation", stale_first_lookup)

    result = executor.execute(rec.id, PLACED_AT)

    assert calls["n"] == 2  # 1 consulta obsoleta + 1 tras el IntegrityError
    assert result.created is False
    assert result.bet.id == winner.id
    assert float(result.bet.stake) == 11.0
    assert db_session.query(Bet).count() == 1
    assert db_session.query(BetLeg).count() == 1
    # La sesion sigue utilizable (transaccion externa intacta).
    assert db_session.query(Opportunity).count() == 1


# --- errores tecnicos -------------------------------------------------------


def test_technical_error_is_propagated_not_converted(db_session, executor, monkeypatch):
    rec, _ = _simple_rec(db_session)

    def boom(self, **kwargs):
        raise OperationalError("INSERT", {}, Exception("db down"))

    monkeypatch.setattr(BetRepository, "create", boom)

    with pytest.raises(OperationalError):
        executor.execute(rec.id, PLACED_AT)
    assert db_session.query(Settlement).count() == 0


def test_unrecoverable_integrity_error_is_propagated(db_session, executor, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    rec, _ = _simple_rec(db_session)

    def fk_violation(self, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("fk"))

    monkeypatch.setattr(BetRepository, "create", fk_violation)

    with pytest.raises(IntegrityError):
        executor.execute(rec.id, PLACED_AT)


# --- separacion con Settlement / bankroll ----------------------------------


def test_executor_does_not_create_settlement_nor_bankroll_movements(db_session, executor):
    rec, _ = _simple_rec(db_session)
    executor.execute(rec.id, PLACED_AT)
    assert db_session.query(Settlement).count() == 0
    assert db_session.query(BankrollTransaction).count() == 0


@pytest.mark.parametrize(
    "leg_result, status, profit_loss",
    [("won", "won", 50.0), ("lost", "lost", -50.0), ("void", "void", 0.0)],
)
def test_simple_trial_can_be_settled_by_settlement_service(db_session, executor, leg_result, status, profit_loss):
    rec, _ = _simple_rec(db_session, odds=2.0, kelly=0.2)
    bet = executor.execute(rec.id, PLACED_AT).bet

    settlement = SettlementService(BetRepository(db_session), SettlementRepository(db_session)).settle_bet(
        bet.id, leg_results={1: leg_result}, settled_at=START
    )

    assert settlement.status == status
    assert float(settlement.profit_loss) == profit_loss
    assert bet.status == "settled"


def test_compound_trial_can_be_settled_as_won(db_session, executor):
    rec, _, _ = _compound_rec(db_session)
    bet = executor.execute(rec.id, PLACED_AT).bet
    stake = float(bet.stake)

    settlement = SettlementService(BetRepository(db_session), SettlementRepository(db_session)).settle_bet(
        bet.id, leg_results={1: "won", 2: "won"}, settled_at=START
    )

    assert settlement.status == "won"
    assert float(settlement.payout) == round(stake * 4.0, 2)


def test_audit_trail_reconstructs_opportunities_from_bet(db_session, executor):
    rec, opps, _ = _compound_rec(db_session)
    bet = executor.execute(rec.id, PLACED_AT).bet
    fetched = RecommendationRepository(db_session).get(bet.recommendation_id)
    linked = {ro.leg_order: ro.opportunity_id for ro in fetched.legs}
    assert [linked[leg.leg_order] for leg in bet.legs] == [o.id for o in opps]
