"""Orquestador de tiempo del Trial (Fase 5.9).

Solo repite, de forma secuencial y en un unico proceso:

    generar now (UTC) -> run_flow(now) -> registrar resultado/error -> esperar

No contiene logica de negocio: la unica accion de dominio es la funcion
`run_flow` inyectada (en produccion, TrialFlowService.run con el bankroll
explicito). Ejecuta un ciclo inmediatamente al arrancar y despues uno por
intervalo. Un ciclo que falla se registra y el loop continua.

Esta version asume UN unico runner: no hay locks ni coordinacion entre procesos.
"""

import logging
import math
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from app.trials.trial_flow_service import TrialFlowResult

logger = logging.getLogger(__name__)


def validate_scheduler_config(*, bankroll: float, interval_seconds: float) -> None:
    if not math.isfinite(bankroll) or bankroll <= 0:
        raise ValueError(f"bankroll debe ser > 0 (recibido: {bankroll})")
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        raise ValueError(f"interval_seconds debe ser > 0 (recibido: {interval_seconds})")


class TrialScheduler:
    def __init__(
        self,
        run_flow: Callable[[datetime], TrialFlowResult],
        *,
        bankroll: float,
        interval_seconds: float,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        wait: Callable[[float], bool] | None = None,
    ):
        """`run_flow(now)` ejecuta un ciclo completo. `wait(seconds)` espera y
        devuelve True si se pidio parar (por defecto, Event.wait sobre el
        evento interno que activa stop())."""
        validate_scheduler_config(bankroll=bankroll, interval_seconds=interval_seconds)
        self._run_flow = run_flow
        self.bankroll = bankroll
        self.interval_seconds = interval_seconds
        self._clock = clock
        self._stop_event = threading.Event()
        self._wait = wait if wait is not None else self._stop_event.wait

    def stop(self) -> None:
        """Pide parar; el ciclo en curso (si hay) termina antes de salir."""
        self._stop_event.set()

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def run_once(self) -> TrialFlowResult | None:
        """Un ciclo. Nunca propaga excepciones de Exception; devuelve None si fallo."""
        now = self._clock()
        try:
            result = self._run_flow(now)
        except Exception:
            logger.exception("Trial cycle failed; scheduler will continue")
            return None
        self._log_result(result)
        return result

    def run_forever(self) -> None:
        logger.info(
            "Trial scheduler started (interval=%ss, bankroll=%s)",
            self.interval_seconds,
            self.bankroll,
        )
        try:
            while not self.stop_requested:
                self.run_once()
                if self._wait(self.interval_seconds) or self.stop_requested:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            logger.info("Trial scheduler stopped")

    @staticmethod
    def _log_result(result: TrialFlowResult) -> None:
        execution_status = result.execution.status
        if result.status == "completed_with_failures":
            logger.warning(
                "Trial cycle completed with failures: settlement_failed=%d execution=%s",
                len(result.settlement.failed),
                execution_status,
            )
        elif execution_status == "no_bet":
            logger.info("Trial cycle completed: no_bet")
        else:
            logger.info("Trial cycle completed")
