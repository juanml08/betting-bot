"""Tests del TrialScheduler: solo comportamiento de tiempo/control, sin DB ni sleeps reales."""

import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.settlements.trial_settlement_service import SettleDueResult
from app.trials.trial_flow_service import TrialFlowResult
from app.trials.trial_scheduler import TrialScheduler

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def _result(*, failed=None, execution_status="executed"):
    settlement = SettleDueResult(failed=failed or [])
    return TrialFlowResult(settlement=settlement, execution=SimpleNamespace(status=execution_status))


def _scheduler(run_flow, events, *, max_waits=2, interval=30.0, stop_on=None):
    """wait falso: registra en `events`, devuelve True (parar) tras max_waits."""
    waits = []

    def wait(seconds):
        events.append(("wait", seconds))
        waits.append(seconds)
        return len(waits) >= max_waits

    return TrialScheduler(
        run_flow, bankroll=500.0, interval_seconds=interval, clock=lambda: NOW, wait=wait
    )


def test_runs_immediately_before_first_wait():
    events = []

    def run_flow(now):
        events.append(("run", now))
        return _result()

    _scheduler(run_flow, events, max_waits=1).run_forever()
    assert events[0] == ("run", NOW)
    assert events[1][0] == "wait"


def test_now_is_utc_aware_by_default():
    seen = []

    def run_flow(now):
        seen.append(now)
        return _result()

    sched = TrialScheduler(run_flow, bankroll=1.0, interval_seconds=1.0, wait=lambda s: True)
    sched.run_forever()
    assert seen[0].tzinfo is not None and seen[0].utcoffset().total_seconds() == 0


def test_waits_configured_interval_and_runs_sequentially():
    events = []

    def run_flow(now):
        events.append(("start", None))
        events.append(("end", None))
        return _result()

    _scheduler(run_flow, events, max_waits=2, interval=42.0).run_forever()
    assert events == [
        ("start", None), ("end", None), ("wait", 42.0),
        ("start", None), ("end", None), ("wait", 42.0),
    ]


def test_cycle_exception_is_logged_and_loop_continues(caplog):
    calls = []

    def run_flow(now):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return _result()

    with caplog.at_level(logging.INFO):
        _scheduler(run_flow, [], max_waits=2).run_forever()

    assert len(calls) == 2
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and errors[0].exc_info is not None


def test_completed_with_failures_logs_warning_and_continues(caplog):
    calls = []

    def run_flow(now):
        calls.append(1)
        return _result(failed=[(7, "db error")])

    with caplog.at_level(logging.INFO):
        _scheduler(run_flow, [], max_waits=2).run_forever()

    assert len(calls) == 2
    assert any(r.levelno == logging.WARNING and "failures" in r.getMessage() for r in caplog.records)


def test_no_bet_logged_and_continues(caplog):
    calls = []

    def run_flow(now):
        calls.append(1)
        return _result(execution_status="no_bet")

    with caplog.at_level(logging.INFO):
        _scheduler(run_flow, [], max_waits=2).run_forever()

    assert len(calls) == 2
    assert any("no_bet" in r.getMessage() for r in caplog.records)
    assert not any(r.levelno >= logging.WARNING for r in caplog.records)


@pytest.mark.parametrize(
    "bankroll,interval",
    [(0, 60), (-1, 60), (500, 0), (500, -5), (float("nan"), 60), (500, float("inf"))],
)
def test_invalid_config_rejected_before_loop(bankroll, interval):
    calls = []
    with pytest.raises(ValueError):
        TrialScheduler(
            lambda now: calls.append(now), bankroll=bankroll, interval_seconds=interval
        )
    assert calls == []


def test_stop_requested_before_start_runs_nothing():
    calls = []
    sched = TrialScheduler(lambda now: calls.append(now), bankroll=1.0, interval_seconds=1.0)
    sched.stop()
    sched.run_forever()
    assert calls == []


def test_stop_during_cycle_finishes_cycle_then_exits(caplog):
    calls = []
    holder = {}

    def run_flow(now):
        calls.append(1)
        holder["s"].stop()  # parada solicitada mientras el ciclo corre
        return _result()

    sched = TrialScheduler(run_flow, bankroll=1.0, interval_seconds=3600.0)
    holder["s"] = sched
    with caplog.at_level(logging.INFO):
        sched.run_forever()  # con la espera real: Event.wait retorna al instante

    assert calls == [1]
    assert any("Trial scheduler stopped" in r.getMessage() for r in caplog.records)


def test_keyboard_interrupt_exits_cleanly(caplog):
    def wait(seconds):
        raise KeyboardInterrupt

    sched = TrialScheduler(
        lambda now: _result(), bankroll=1.0, interval_seconds=1.0, wait=wait
    )
    with caplog.at_level(logging.INFO):
        sched.run_forever()
    assert any("Trial scheduler stopped" in r.getMessage() for r in caplog.records)
