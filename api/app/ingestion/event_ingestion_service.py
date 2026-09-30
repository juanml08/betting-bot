"""Ingesta de estado/resultado de eventos (Fase 5.11).

    EventUpdateProvider -> EventUpdate -> EventIngestionService -> Event

Solo actualiza Event.status y Event.result. NO crea Settlement, no toca Bet,
BetLeg ni Opportunity, y no interpreta el resultado (won/lost/void): eso lo
hace TrialSettlementService/result_resolver en el siguiente ciclo. Tampoco crea
eventos: un external_id desconocido se reporta, no se inserta.

Reglas de datos (sin estados nuevos; se reutiliza el vocabulario del dominio):
- status debe ser un EventStatus. result debe ser una clave de
  _RESULT_TO_SELECTION (home_win/away_win/draw), el mismo vocabulario que usa
  result_resolver.
- 'finished' EXIGE result: sin el, la Bet quedaria sin resolver; se rechaza y
  el evento conserva su estado hasta que llegue el dato completo.
- scheduled/live/cancelled NO admiten result.

Transiciones permitidas:
    scheduled -> live | finished | cancelled
    live      -> finished | cancelled
'finished' y 'cancelled' son terminales. Mismo status y mismo resultado es
'unchanged' (idempotencia). Todo lo demas se rechaza, incluido corregir el
resultado de un evento ya finished: puede haber Bets liquidadas con el
resultado anterior, asi que corregirlo es una decision manual.

Transaccion: una por evento (commit / rollback aislado). Un fallo tecnico en un
evento no afecta a los demas y se reporta en `failed`.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from backtesting.engine import _RESULT_TO_SELECTION

from app.db.repositories.event_repository import EventRepository
from app.domain.interfaces import EventUpdateProvider
from app.domain.models import EventStatus, EventUpdate

logger = logging.getLogger(__name__)

_VALID_STATUSES = frozenset(s.value for s in EventStatus)
_VALID_RESULTS = frozenset(_RESULT_TO_SELECTION)
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "scheduled": frozenset({"live", "finished", "cancelled"}),
    "live": frozenset({"finished", "cancelled"}),
    "finished": frozenset(),
    "cancelled": frozenset(),
}


@dataclass
class IngestionResult:
    processed: int = 0
    updated: list[str] = field(default_factory=list)  # external_id actualizados
    unchanged: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)  # external_id inexistentes en la BD
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (external_id, motivo): dato o transicion invalida
    failed: list[tuple[str, str]] = field(default_factory=list)  # (external_id, error tecnico)


class EventIngestionService:
    def __init__(self, db: Session, event_repository: EventRepository | None = None):
        self._db = db
        self._events = event_repository or EventRepository(db)

    def sync(self, provider: EventUpdateProvider) -> IngestionResult:
        """Pide las actualizaciones al proveedor y las ingesta. Si el proveedor
        falla, la excepcion se propaga sin haber tocado la BD."""
        return self.ingest(provider.get_event_updates())

    def ingest(self, updates: list[EventUpdate]) -> IngestionResult:
        result = IngestionResult()
        for update in updates:
            result.processed += 1
            try:
                outcome, detail = self._apply(update)
                self._db.commit()
            except Exception as exc:
                self._db.rollback()
                logger.exception("Fallo tecnico ingestando evento %s", update.external_id)
                result.failed.append((update.external_id, f"{type(exc).__name__}: {exc}"))
                continue
            if outcome == "rejected":
                result.rejected.append((update.external_id, detail))
            else:
                getattr(result, outcome).append(update.external_id)
        logger.info(
            "Event ingestion: processed=%d updated=%d unchanged=%d unknown=%d rejected=%d failed=%d",
            result.processed, len(result.updated), len(result.unchanged),
            len(result.unknown), len(result.rejected), len(result.failed),
        )
        return result

    def _apply(self, update: EventUpdate) -> tuple[str, str]:
        error = self._validate_shape(update)
        if error:
            logger.error("Invalid update for event %s: %s", update.external_id, error)
            return "rejected", error

        event = self._events.get_by_external_id(update.external_id)
        if event is None:
            logger.warning("Unknown event %s received", update.external_id)
            return "unknown", ""

        current = event.status
        if update.status == current:
            if update.result == event.result:
                logger.debug("Event %s already up to date", update.external_id)
                return "unchanged", ""
            error = f"evento {current} no admite cambiar el resultado ({event.result!r} -> {update.result!r})"
        elif update.status not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            error = f"transicion invalida {current} -> {update.status}"
        else:
            error = None
        if error:
            logger.error("Rejected update for event %s: %s", update.external_id, error)
            return "rejected", error

        self._events.apply_update(event, status=update.status, result=update.result)
        logger.info(
            "Event %s updated %s -> %s%s", update.external_id, current, update.status,
            f" ({update.result})" if update.result else "",
        )
        return "updated", ""

    @staticmethod
    def _validate_shape(update: EventUpdate) -> str | None:
        if update.status not in _VALID_STATUSES:
            return f"status invalido: {update.status!r}"
        if update.status == "finished":
            if update.result is None:
                return "un evento finished requiere result"
            if update.result not in _VALID_RESULTS:
                return f"result invalido: {update.result!r} (esperado {sorted(_VALID_RESULTS)})"
        elif update.result is not None:
            return f"status {update.status!r} no admite result ({update.result!r})"
        return None
