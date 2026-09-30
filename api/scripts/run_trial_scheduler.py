"""Ejecuta el Trial Flow periodicamente (un unico runner por entorno).

Ejecuta un ciclo inmediatamente y luego uno cada --interval-seconds.
Ctrl+C / SIGTERM detienen el proceso de forma limpia.

Uso:
    poetry run python scripts/run_trial_scheduler.py --bankroll 500
    poetry run python scripts/run_trial_scheduler.py --bankroll 500 --interval-seconds 60
"""

import argparse
import signal
from datetime import datetime

from app.api.deps import get_risk_manager
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.settlements.trial_settlement_service import TrialSettlementService
from app.trials.trial_flow_service import TrialFlowResult, TrialFlowService
from app.trials.trial_scheduler import TrialScheduler, validate_scheduler_config
from app.trials.trial_service import TrialService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bankroll", type=float, required=True, help="Bankroll trial (> 0) usado en cada ciclo")
    parser.add_argument("--interval-seconds", type=float, default=60, help="Segundos entre ciclos (> 0, default 60)")
    args = parser.parse_args()

    try:
        validate_scheduler_config(bankroll=args.bankroll, interval_seconds=args.interval_seconds)
    except ValueError as exc:
        parser.error(str(exc))

    configure_logging()
    risk_manager = get_risk_manager(get_settings())

    def run_flow(now: datetime) -> TrialFlowResult:
        # Sesion nueva por ciclo: evita arrastrar estado/conexiones entre ciclos.
        db = SessionLocal()
        try:
            flow = TrialFlowService(TrialSettlementService(db), TrialService(db, risk_manager))
            return flow.run(now=now, bankroll=args.bankroll)
        finally:
            db.close()

    scheduler = TrialScheduler(run_flow, bankroll=args.bankroll, interval_seconds=args.interval_seconds)
    signal.signal(signal.SIGTERM, lambda *_: scheduler.stop())
    scheduler.run_forever()


if __name__ == "__main__":
    main()
