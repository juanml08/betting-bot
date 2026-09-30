"""Acceso a datos de Opportunity.

Las operaciones de lifecycle (heartbeat / superseded / expired) son UPDATE
condicionales y devuelven True solo si cambiaron una fila, de modo que sean
monotonicas e idempotentes aunque dos procesos las ejecuten a la vez. Solo
hacen flush, nunca commit: la transaccion es del OpportunityLifecycleService.

Los datetimes se comparan y guardan como naive UTC (convencion del proyecto).
"""

from datetime import datetime, timedelta

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from app.db.models import Event, Opportunity
from app.opportunities.opportunity_service import OpportunityCandidate
from app.opportunities.slot import to_naive_utc

_CANDIDATE = "candidate"
_SUPERSEDED = "superseded"
_EXPIRED = "expired"
_EVENT_SCHEDULED = "scheduled"


class OpportunityRepository:
    def __init__(self, db: Session):
        self._db = db

    def list_candidates(self, *, status: str | None = None) -> list[Opportunity]:
        stmt = select(Opportunity)
        if status:
            stmt = stmt.where(Opportunity.status == status)
        return list(self._db.scalars(stmt.order_by(Opportunity.created_at.desc())))

    def list_eligible(self, *, now: datetime, ttl: timedelta) -> list[Opportunity]:
        """Opportunities que pueden entrar a una decision: 'candidate', dentro
        del TTL (now - last_observed_at <= ttl) y de un evento 'scheduled' que
        aun no empezo. El TTL se evalua aqui, al leer: no depende de ningun job
        que expire filas."""
        now_db = to_naive_utc(now)
        stmt = (
            select(Opportunity)
            .join(Event, Event.id == Opportunity.event_id)
            .where(
                Opportunity.status == _CANDIDATE,
                Opportunity.last_observed_at >= now_db - ttl,
                Event.status == _EVENT_SCHEDULED,
                Event.start_time > now_db,
            )
            .order_by(Opportunity.id)
        )
        return list(self._db.scalars(stmt))

    def find_latest_version(
        self, *, event_id: int, market_type: str, selection: str, bookmaker: str
    ) -> Opportunity | None:
        """Ultima version del slot (la vigente si esta 'candidate'; si esta
        'expired' el slot no tiene candidata vigente). Las columnas de
        identidad deben venir ya normalizadas."""
        stmt = (
            select(Opportunity)
            .where(
                Opportunity.event_id == event_id,
                Opportunity.market_type == market_type,
                Opportunity.selection == selection,
                Opportunity.bookmaker == bookmaker,
            )
            .order_by(Opportunity.version.desc())
            .limit(1)
        )
        return self._db.scalars(stmt.execution_options(populate_existing=True)).first()

    def create_version(
        self,
        candidate: OpportunityCandidate,
        *,
        event_id: int,
        market_type: str,
        selection: str,
        bookmaker: str,
        version: int,
        observed_at: datetime,
        created_at: datetime,
        probability_estimate_id: int | None = None,
    ) -> Opportunity:
        """Inserta una version 'candidate'. Puede lanzar IntegrityError si otra
        transaccion ya creo esa version del slot (UNIQUE); el llamador debe
        hacer rollback."""
        opp = candidate.opportunity
        record = Opportunity(
            event_id=event_id,
            probability_estimate_id=probability_estimate_id,
            market_type=market_type,
            selection=selection,
            bookmaker=bookmaker,
            odds_value=opp.odds_value,
            estimated_probability=opp.estimated_probability,
            implied_probability=opp.implied_probability,
            edge=opp.edge,
            expected_value=opp.expected_value,
            kelly_fraction_suggested=opp.kelly_fraction_suggested,
            suggested_stake=candidate.suggested_stake,
            status=_CANDIDATE,
            created_at=to_naive_utc(created_at),
            version=version,
            last_observed_at=to_naive_utc(observed_at),
        )
        self._db.add(record)
        self._db.flush()
        return record

    def heartbeat(self, opportunity: Opportunity, observed_at: datetime) -> bool:
        """Avanza last_observed_at solo si la observacion es mas nueva."""
        observed = to_naive_utc(observed_at)
        result = self._db.execute(
            update(Opportunity)
            .where(
                Opportunity.id == opportunity.id,
                Opportunity.status == _CANDIDATE,
                Opportunity.last_observed_at < observed,
            )
            .values(last_observed_at=observed)
            .execution_options(synchronize_session=False)
        )
        self._refresh(opportunity)
        return result.rowcount > 0

    def mark_superseded(
        self, opportunity: Opportunity, *, successor_id: int, superseded_at: datetime
    ) -> bool:
        """candidate -> superseded (idempotente: WHERE status = 'candidate')."""
        superseded = to_naive_utc(superseded_at)
        result = self._db.execute(
            update(Opportunity)
            .where(Opportunity.id == opportunity.id, Opportunity.status == _CANDIDATE)
            .values(
                status=_SUPERSEDED,
                superseded_at=superseded,
                superseded_by_id=successor_id,
            )
            .execution_options(synchronize_session=False)
        )
        self._refresh(opportunity)
        return result.rowcount > 0

    def mark_expired(self, opportunity: Opportunity, observed_at: datetime) -> bool:
        """candidate -> expired (idempotente: WHERE status = 'candidate').
        last_observed_at avanza (monotonico) al instante de la observacion que
        la cerro, para que una observacion anterior que llegue tarde no pueda
        resucitar el slot."""
        observed = to_naive_utc(observed_at)
        result = self._db.execute(
            update(Opportunity)
            .where(Opportunity.id == opportunity.id, Opportunity.status == _CANDIDATE)
            .values(
                status=_EXPIRED,
                last_observed_at=case(
                    (Opportunity.last_observed_at < observed, observed),
                    else_=Opportunity.last_observed_at,
                ),
            )
            .execution_options(synchronize_session=False)
        )
        self._refresh(opportunity)
        return result.rowcount > 0

    def list_current_candidates_for_events(self, event_ids: list[int]) -> list[Opportunity]:
        if not event_ids:
            return []
        stmt = select(Opportunity).where(
            Opportunity.event_id.in_(event_ids), Opportunity.status == _CANDIDATE
        )
        return list(self._db.scalars(stmt.execution_options(populate_existing=True)))

    def _refresh(self, opportunity: Opportunity) -> None:
        self._db.refresh(opportunity)
