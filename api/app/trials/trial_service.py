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

Elegibilidad: OpportunityRepository.list_eligible (status candidate, TTL sobre
last_observed_at, evento scheduled y futuro). Este servicio solo agrega la
regla propia de Trial descrita abajo.

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
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Bet, BetLeg, Opportunity, Recommendation
from app.db.repositories.opportunity_repository import OpportunityRepository
from app.db.repositories.recommendation_repository import RecommendationRepository
from app.decisions.decision_engine import DecisionEngine
from app.domain.interfaces import RiskManager
from app.recommendations.recommendation_service import RecommendationService
from app.trials.trial_executor import TrialExecutor

_MODE = "trial"
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
        opportunity_ttl: timedelta | None = None,
    ):
        self._db = db
        self._opportunity_repo = OpportunityRepository(db)
        self._opportunity_ttl = opportunity_ttl or timedelta(
            seconds=get_settings().opportunity_ttl_seconds
        )
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
        # Frescura (candidate + TTL) y elegibilidad del evento (scheduled, no
        # iniciado) las resuelve el repository; aqui solo la regla de Trial.
        eligible = self._opportunity_repo.list_eligible(now=placed_at, ttl=self._opportunity_ttl)
        return [o for o in eligible if o.event_id not in open_event_ids]
