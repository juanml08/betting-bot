"""Ejecuta una vez el Trial Flow completo: settle_due -> run_cycle.

Uso: poetry run python scripts/run_trial.py --bankroll 500
"""

import argparse
from datetime import datetime, timezone

from app.api.deps import get_risk_manager
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.settlements.trial_settlement_service import TrialSettlementService
from app.trials.trial_flow_service import TrialFlowService
from app.trials.trial_service import TrialService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bankroll", type=float, required=True, help="Bankroll trial para este ciclo")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        flow = TrialFlowService(
            TrialSettlementService(db),
            TrialService(db, get_risk_manager(get_settings())),
        )
        result = flow.run(now=datetime.now(timezone.utc), bankroll=args.bankroll)

        s, e = result.settlement, result.execution
        print("=== Trial Flow ===")
        print(f"Status: {result.status}\n")
        print("Settlement:")
        print(f"  processed: {s.processed}")
        print(f"  settled: {len(s.settled)}")
        print(f"  unresolved: {len(s.unresolved)}")
        print(f"  already_settled: {len(s.already_settled)}")
        print(f"  failed: {len(s.failed)}")
        for bet_id, error in s.failed:
            print(f"    bet {bet_id}: {error}")
        print("\nExecution:")
        print(f"  status: {e.status}")
        if e.reason:
            print(f"  reason: {e.reason}")
        print(f"  recommendation_id: {e.recommendation.id}")
        if e.bet is not None:
            print(f"  bet_id: {e.bet.id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
