"""Entrypoint del Trial Flow: coordina, en este orden,

    1. TrialSettlementService.settle_due(settled_at=now)
    2. TrialService.run_cycle(placed_at=now, bankroll=bankroll)

Primero se cierra lo que ya termino (Bets pendientes del ciclo anterior) y
despues se buscan nuevas Opportunities. Solo coordina: no contiene logica de
negocio de ninguna de las dos piezas.

Transacciones: no hay transaccion global. settle_due commitea por Bet y
run_cycle tiene su propia unidad (commit/rollback), asi que un fallo al
ejecutar no revierte settlements ya confirmados.

Errores: los fallos tecnicos por Bet de settle_due quedan en
`settlement.failed` y el flujo continua. Cualquier excepcion de run_cycle se
propaga tal cual (no se convierte en no_bet).

El bankroll es un parametro explicito (igual que en 5.6): aqui no se consulta
ni se modifica ningun saldo.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from app.settlements.trial_settlement_service import SettleDueResult, TrialSettlementService
from app.trials.trial_service import TrialCycleResult, TrialService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrialFlowResult:
    settlement: SettleDueResult
    execution: TrialCycleResult

    @property
    def status(self) -> str:
        """'success' si no hubo fallos tecnicos en settlement;
        'completed_with_failures' si alguna Bet fallo (ver settlement.failed)."""
        return "completed_with_failures" if self.settlement.failed else "success"


class TrialFlowService:
    def __init__(self, settlement_service: TrialSettlementService, trial_service: TrialService):
        self._settlement_service = settlement_service
        self._trial_service = trial_service

    def run(self, *, now: datetime, bankroll: float) -> TrialFlowResult:
        logger.info("Trial flow started (now=%s)", now.isoformat())

        settlement = self._settlement_service.settle_due(settled_at=now)
        logger.info(
            "Trial settlement completed: processed=%d settled=%d unresolved=%d "
            "already_settled=%d failed=%d",
            settlement.processed,
            len(settlement.settled),
            len(settlement.unresolved),
            len(settlement.already_settled),
            len(settlement.failed),
        )

        execution = self._trial_service.run_cycle(placed_at=now, bankroll=bankroll)
        logger.info("Trial execution completed: status=%s", execution.status)

        result = TrialFlowResult(settlement=settlement, execution=execution)
        logger.info("Trial flow completed: %s", result.status)
        return result
