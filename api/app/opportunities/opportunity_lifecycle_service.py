"""Ciclo de vida de Opportunity: versionado inmutable por slot.

Slot = (event_id, market_type, selection, bookmaker), con strings normalizadas
(strip + lower). Recibe la observacion del pipeline (OpportunityObservation) y
decide, por slot y comparando siempre contra la ULTIMA version:

- sin version previa            -> v1 'candidate'                    (CREATED)
- captured_at <= last_observed  -> se ignora, sin efectos            (IGNORED_STALE)
- misma cuota y probabilidad    -> solo avanza last_observed_at      (HEARTBEAT)
- cambia cuota o probabilidad   -> version N+1 'candidate' y la
                                   anterior pasa a 'superseded'      (NEW_VERSION)
- ultima version 'expired'      -> version N+1 'candidate'           (NEW_VERSION)
- slot observado que ya no
  califica, o que ya no aparece
  en un evento evaluado         -> 'candidate' pasa a 'expired'      (EXPIRED)

captured_at (cuando el proveedor observo la cuota) es lo que decide la
frescura; created_at (cuando se persiste) viene del reloj del servicio.

Transacciones y concurrencia: la sesion debe llegar limpia (como en
TrialService: un rollback descarta lo no commiteado). Cada slot se procesa en su propia transaccion
(commit por slot). Si dos procesos intentan crear la misma version, el UNIQUE
(slot, version) hace fallar a uno con IntegrityError: se hace rollback, se abre
una transaccion nueva, se relee el slot y se resuelve de nuevo (puede terminar
en heartbeat, nueva version o ignorado). No se sigue usando una transaccion
despues de un IntegrityError. Consecuencia: una generacion no es atomica en
conjunto; cada slot lo es.

OpportunityService solo calcula oportunidades; este servicio es el unico que
escribe el ciclo de vida.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Opportunity
from app.db.repositories.event_repository import EventRepository
from app.db.repositories.opportunity_repository import OpportunityRepository
from app.opportunities.opportunity_service import OpportunityCandidate, OpportunityObservation
from app.opportunities.slot import SlotKey, to_naive_utc

_CANDIDATE = "candidate"
_ODDS_PLACES = 2  # Numeric(6, 2)
_PROBABILITY_PLACES = 5  # Numeric(6, 5)
_DEFAULT_MAX_ATTEMPTS = 3


class SlotAction(StrEnum):
    CREATED = "created"
    NEW_VERSION = "new_version"
    HEARTBEAT = "heartbeat"
    IGNORED_STALE = "ignored_stale"
    EXPIRED = "expired"
    NOOP = "noop"


@dataclass(frozen=True)
class SlotOutcome:
    action: SlotAction
    opportunity: Opportunity | None


@dataclass
class LifecycleResult:
    outcomes: list[SlotOutcome] = field(default_factory=list)

    @property
    def current_candidates(self) -> list[Opportunity]:
        """Version vigente ('candidate') de cada slot candidato de la pasada."""
        return [
            o.opportunity
            for o in self.outcomes
            if o.opportunity is not None
            and o.opportunity.status == _CANDIDATE
            and o.action
            in (
                SlotAction.CREATED,
                SlotAction.NEW_VERSION,
                SlotAction.HEARTBEAT,
                SlotAction.IGNORED_STALE,
            )
        ]

    def count(self, action: SlotAction) -> int:
        return sum(1 for o in self.outcomes if o.action == action)


class UnknownEventError(Exception):
    """Una candidata referencia un evento que no esta en la base de datos."""

    def __init__(self, external_ids: list[str]):
        self.external_ids = external_ids
        super().__init__(f"Eventos no encontrados en la base de datos: {sorted(external_ids)}")


class _SlotConflict(Exception):
    """Otra transaccion cambio el slot entre la lectura y la escritura."""


class OpportunityLifecycleService:
    def __init__(
        self,
        db: Session,
        *,
        clock: Callable[[], datetime] | None = None,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    ):
        self._db = db
        self._repo = OpportunityRepository(db)
        self._events = EventRepository(db)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._max_attempts = max_attempts

    def apply(self, observation: OpportunityObservation) -> LifecycleResult:
        candidate_events = {c.opportunity.event_external_id for c in observation.candidates}
        event_ids: dict[str, int] = {}
        missing: list[str] = []
        for external_id in (
            candidate_events
            | {s.key.event_ref for s in observation.non_qualifying}
            | set(observation.evaluated_events)
        ):
            event = self._events.get_by_external_id(external_id)
            if event is not None:
                event_ids[external_id] = event.id
            elif external_id in candidate_events:
                missing.append(external_id)
        if missing:
            raise UnknownEventError(missing)  # antes de escribir nada
        self._db.commit()  # cierra la transaccion de lectura (snapshot fresco por slot)

        result = LifecycleResult()
        seen: set[SlotKey] = set()

        for candidate in observation.candidates:
            opp = candidate.opportunity
            key = SlotKey.of(
                event_ids[opp.event_external_id], opp.market_type, opp.selection, opp.bookmaker
            )
            seen.add(key)
            result.outcomes.append(
                self._in_transaction(lambda c=candidate, k=key: self._apply_candidate(k, c))
            )

        for slot in observation.non_qualifying:
            event_id = event_ids.get(slot.key.event_ref)
            if event_id is None:
                continue
            key = SlotKey(event_id, slot.key.market_type, slot.key.selection, slot.key.bookmaker)
            seen.add(key)
            result.outcomes.append(
                self._in_transaction(lambda k=key, at=slot.captured_at: self._apply_close(k, at))
            )

        result.outcomes.extend(self._close_absent_slots(observation, event_ids, seen))
        return result

    # -- por slot ---------------------------------------------------------

    def _apply_candidate(self, key: SlotKey, candidate: OpportunityCandidate) -> SlotOutcome:
        if candidate.captured_at is None:
            raise ValueError("captured_at es obligatorio: es el instante de observacion del proveedor")
        captured_at = to_naive_utc(candidate.captured_at)
        latest = self._latest(key)

        if latest is None:
            return SlotOutcome(SlotAction.CREATED, self._create(key, candidate, 1, captured_at))

        if captured_at <= latest.last_observed_at:
            return SlotOutcome(SlotAction.IGNORED_STALE, latest)

        if latest.status != _CANDIDATE:
            return SlotOutcome(
                SlotAction.NEW_VERSION, self._create(key, candidate, latest.version + 1, captured_at)
            )

        if _same_decision(latest, candidate):
            self._repo.heartbeat(latest, captured_at)
            return SlotOutcome(SlotAction.HEARTBEAT, latest)

        successor = self._create(key, candidate, latest.version + 1, captured_at)
        if not self._repo.mark_superseded(
            latest, successor_id=successor.id, superseded_at=captured_at
        ):
            raise _SlotConflict(f"Opportunity {latest.id} dejo de ser candidate")
        return SlotOutcome(SlotAction.NEW_VERSION, successor)

    def _apply_close(self, key: SlotKey, observed_at: datetime) -> SlotOutcome:
        observed = to_naive_utc(observed_at)
        latest = self._latest(key)
        if latest is None or latest.status != _CANDIDATE:
            return SlotOutcome(SlotAction.NOOP, latest)
        if observed <= latest.last_observed_at:
            return SlotOutcome(SlotAction.IGNORED_STALE, latest)
        if not self._repo.mark_expired(latest, observed):
            return SlotOutcome(SlotAction.NOOP, latest)  # ya cerrada por otro proceso
        return SlotOutcome(SlotAction.EXPIRED, latest)

    def _close_absent_slots(
        self, observation: OpportunityObservation, event_ids: dict[str, int], seen: set[SlotKey]
    ) -> list[SlotOutcome]:
        """Candidatas vigentes de eventos evaluados cuyo slot no aparecio en la pasada."""
        observed_at_by_event = {
            event_ids[ext]: at for ext, at in observation.evaluated_events.items() if ext in event_ids
        }
        current = self._repo.list_current_candidates_for_events(list(observed_at_by_event))
        absent = [
            (
                SlotKey(o.event_id, o.market_type, o.selection, o.bookmaker),
                observed_at_by_event[o.event_id],
            )
            for o in current
            if SlotKey(o.event_id, o.market_type, o.selection, o.bookmaker) not in seen
        ]
        self._db.commit()
        return [
            self._in_transaction(lambda k=key, at=observed_at: self._apply_close(k, at))
            for key, observed_at in absent
        ]

    # -- helpers ----------------------------------------------------------

    def _latest(self, key: SlotKey) -> Opportunity | None:
        return self._repo.find_latest_version(
            event_id=key.event_ref,
            market_type=key.market_type,
            selection=key.selection,
            bookmaker=key.bookmaker,
        )

    def _create(
        self, key: SlotKey, candidate: OpportunityCandidate, version: int, observed_at: datetime
    ) -> Opportunity:
        return self._repo.create_version(
            candidate,
            event_id=key.event_ref,
            market_type=key.market_type,
            selection=key.selection,
            bookmaker=key.bookmaker,
            version=version,
            observed_at=observed_at,
            created_at=self._clock(),
        )

    def _in_transaction(self, operation: Callable[[], SlotOutcome]) -> SlotOutcome:
        for attempt in range(1, self._max_attempts + 1):
            try:
                outcome = operation()
                self._db.commit()
                return outcome
            except (IntegrityError, _SlotConflict):
                self._db.rollback()
                if attempt == self._max_attempts:
                    raise
            except Exception:
                self._db.rollback()
                raise
        raise AssertionError("unreachable")  # pragma: no cover


def _same_decision(latest: Opportunity, candidate: OpportunityCandidate) -> bool:
    """Compara al mismo redondeo con el que se persiste (Numeric(6,2) / (6,5))."""
    opp = candidate.opportunity
    return round(float(latest.odds_value), _ODDS_PLACES) == round(opp.odds_value, _ODDS_PLACES) and round(
        float(latest.estimated_probability), _PROBABILITY_PLACES
    ) == round(opp.estimated_probability, _PROBABILITY_PLACES)
