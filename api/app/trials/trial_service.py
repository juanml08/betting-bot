"""Trial Service: orquesta un ciclo "decidir -> ejecutar" del flujo TRIAL.

    Opportunity elegibles -> DecisionEngine -> RecommendationService
        -> Recommendation -> TrialExecutor -> Bet(pending)

Solo orquesta: no calcula EV, G*, Kelly ni stake, no selecciona legs y no crea
Bet/BetLeg/Recommendation por su cuenta. Cada responsabilidad sigue en su
componente (DecisionEngine, RecommendationService, TrialExecutor).

Transaccion: este servicio es el dueno de la unidad Recommendation + Bet.
Los repositorios y servicios solo hacen flush; aqui se hace el unico commit
del ciclo, o rollback si algo falla (la excepcion se propaga sin convertirse
en ningun resultado de negocio). La sesion debe llegar limpia (sin cambios
pendientes de otros procesos): un rollback descarta todo lo no commiteado.

'no_bet' se persiste como Recommendation (auditoria) y se commitea sin llamar
al executor. Un ciclo sin Opportunities elegibles tambien es un 'no_bet'.

Anti-duplicados (pre-filtro, sin migracion): se excluyen las Opportunity de
eventos que ya tienen un Bet trial abierto (Bet.mode='trial' y
Bet.status='pending', incluye un Bet cuyo Settlement quedo en manual_review).
Es un check-then-act: solo es seguro con un unico runner; dos ciclos
concurrentes podrian apostar el mismo evento (no hay constraint que lo impida).

Bankroll: parametro explicito del ciclo, se registra en
Recommendation.bankroll_at_recommendation. No se consulta ni se crea ningun
BankrollTransaction y no se descuenta el stake.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Bet, BetLeg, Event, Opportunity, Recommendation
from app.db.repositories.recommendation_repository import RecommendationRepository
from app.decisions.decision_engine import DecisionEngine
from app.domain.interfaces import RiskManager
from app.recommendations.recommendation_service import RecommendationService
from app.trials.trial_executor import TrialExecutor

_MODE = "trial"
_ELIGIBLE_OPPORTUNITY_STATUS = "candidate"
_ELIGIBLE_EVENT_STATUS = "scheduled"
_OPEN_BET_STATUS = "pending"
_DEFAULT_STRATEGY_NAME = "decision_engine"


@dataclass(frozen=True)
class TrialCycleResult:
    status: str  # 'executed' | 'no_bet'
    recommendation: Recommendation
    bet: Bet | None  # None solo para 'no_bet'
    eligible_opportunity_ids: list[int]
    reason: str | None = None  # 'no_bet' cuando no hubo ejecucion


class TrialService:
    def __init__(
        self,
        db: Session,
        risk_manager: RiskManager,
        decision_engine: DecisionEngine | None = None,
        *,
        strategy_name: str = _DEFAULT_STRATEGY_NAME,
        strategy_params: dict | None = None,
    ):
        self._db = db
        self._decision_engine = decision_engine or DecisionEngine()
        self._recommendation_service = RecommendationService(RecommendationRepository(db))
        self._executor = TrialExecutor(db, risk_manager)
        self._strategy_name = strategy_name
        self._strategy_params = dict(strategy_params or {})

    def run_cycle(self, *, placed_at: datetime, bankroll: float) -> TrialCycleResult:
        try:
            result = self._run(placed_at, bankroll)
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return result

    def _run(self, placed_at: datetime, bankroll: float) -> TrialCycleResult:
        eligible = self._eligible_opportunities(placed_at)
        eligible_ids = [o.id for o in eligible]

        decision = self._decision_engine.decide(eligible, _MODE)
        recommendation = self._recommendation_service.create_recommendation(
            mode=decision.mode,
            strategy_name=self._strategy_name,
            strategy_params=self._strategy_params,
            bet_type=decision.bet_type,
            bankroll_at_recommendation=bankroll,
            opportunity_ids=decision.opportunity_ids,
            generated_at=placed_at,
            explanation=decision.explanation,
            decision_metadata=decision.decision_metadata,
        )

        if decision.bet_type == "no_bet":
            return TrialCycleResult("no_bet", recommendation, None, eligible_ids, reason="no_bet")

        execution = self._executor.execute(recommendation.id, placed_at)
        return TrialCycleResult("executed", recommendation, execution.bet, eligible_ids)

    def _eligible_opportunities(self, placed_at: datetime) -> list[Opportunity]:
        open_event_ids = set(
            self._db.scalars(
                select(BetLeg.event_id)
                .join(Bet, Bet.id == BetLeg.bet_id)
                .where(Bet.mode == _MODE, Bet.status == _OPEN_BET_STATUS)
            )
        )
        now = _as_utc(placed_at)
        rows = self._db.execute(
            select(Opportunity, Event)
            .join(Event, Event.id == Opportunity.event_id)
            .where(
                Opportunity.status == _ELIGIBLE_OPPORTUNITY_STATUS,
                Event.status == _ELIGIBLE_EVENT_STATUS,
            )
            .order_by(Opportunity.id)
        )
        return [
            o
            for o, event in rows
            if event.id not in open_event_ids and _as_utc(event.start_time) > now
        ]


def _as_utc(value: datetime) -> datetime:
    """MySQL y SQLite devuelven datetimes naive; se asume UTC (igual que TrialExecutor)."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
