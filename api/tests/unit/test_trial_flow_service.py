from datetime import datetime, timezone

import pytest

from app.settlements.trial_settlement_service import SettleDueResult
from app.trials.trial_flow_service import TrialFlowService
from app.trials.trial_service import TrialCycleResult

NOW = datetime(2026, 1, 6, 12, 0, tzinfo=timezone.utc)


class FakeSettlement:
    def __init__(self, calls, result=None):
        self.calls, self.result = calls, result or SettleDueResult()

    def settle_due(self, **kwargs):
        self.calls.append(("settle_due", kwargs))
        return self.result


class FakeTrial:
    def __init__(self, calls, result=None, error=None):
        self.calls, self.result, self.error = calls, result, error

    def run_cycle(self, **kwargs):
        self.calls.append(("run_cycle", kwargs))
        if self.error:
            raise self.error
        return self.result or TrialCycleResult("no_bet", None, None, [], reason="no_bet")


def _flow(calls, settlement=None, trial=None):
    return TrialFlowService(settlement or FakeSettlement(calls), trial or FakeTrial(calls))


def test_settle_due_runs_before_run_cycle():
    calls = []
    _flow(calls).run(now=NOW, bankroll=500.0)
    assert [c[0] for c in calls] == ["settle_due", "run_cycle"]


def test_same_now_and_bankroll_passed():
    calls = []
    _flow(calls).run(now=NOW, bankroll=500.0)
    assert calls[0][1] == {"settled_at": NOW}
    assert calls[1][1] == {"placed_at": NOW, "bankroll": 500.0}


def test_partial_settlement_failure_does_not_block_execution():
    calls = []
    partial = SettleDueResult(processed=4, settled=[1, 2], unresolved=[3], failed=[(4, "RuntimeError: x")])
    result = _flow(calls, FakeSettlement(calls, partial)).run(now=NOW, bankroll=100.0)
    assert [c[0] for c in calls] == ["settle_due", "run_cycle"]
    assert result.settlement is partial and result.settlement.failed == [(4, "RuntimeError: x")]
    assert result.status == "completed_with_failures"


def test_no_bet_keeps_both_results():
    calls = []
    settlement = SettleDueResult(processed=1, settled=[7])
    result = _flow(calls, FakeSettlement(calls, settlement)).run(now=NOW, bankroll=100.0)
    assert result.settlement is settlement
    assert result.execution.status == "no_bet" and result.execution.bet is None
    assert result.status == "success"


def test_run_cycle_error_propagates():
    calls = []
    flow = _flow(calls, trial=FakeTrial(calls, error=RuntimeError("db down")))
    with pytest.raises(RuntimeError, match="db down"):
        flow.run(now=NOW, bankroll=100.0)
    assert [c[0] for c in calls] == ["settle_due", "run_cycle"]


def test_already_settled_continues_normally():
    calls = []
    settlement = SettleDueResult(processed=1, already_settled=[3])
    result = _flow(calls, FakeSettlement(calls, settlement)).run(now=NOW, bankroll=100.0)
    assert [c[0] for c in calls] == ["settle_due", "run_cycle"]
    assert result.status == "success"


def test_settlement_exception_does_not_reach_run_cycle():
    calls = []

    class Boom(FakeSettlement):
        def settle_due(self, **kwargs):
            raise RuntimeError("fatal")

    with pytest.raises(RuntimeError):
        _flow(calls, settlement=Boom(calls)).run(now=NOW, bankroll=1.0)
    assert calls == []
