"""Trial Executor: convierte una Recommendation ya decidida (mode='trial') en
un Bet 'pending' con sus BetLeg, usando dinero ficticio.

Flujo:  Recommendation -> validacion -> RiskManager (stake) -> Bet -> BetLeg(s)

Responsabilidades y limites:
- NO decide (no selecciona, no recalcula EV, G*, Kelly ni poda): eso es del
  DecisionEngine. Solo ejecuta lo que la Recommendation ya trae.
- NO liquida: el Bet queda 'pending'; SettlementService es el unico que
  calcula won/lost/void/manual_review y el payout.
- NO mueve BankrollTransaction: el ledger ficticio de TRIAL es una fase futura.
  El stake se calcula sobre Recommendation.bankroll_at_recommendation.
- 'no_bet' es un resultado explicito (bet=None), nunca crea Bet ni BetLeg.
- Errores de negocio -> RecommendationNotFoundError /
  RecommendationNotExecutableError. Errores tecnicos (SQLAlchemyError,
  IntegrityError no recuperable, ...) se propagan sin convertirse en ningun
  resultado de negocio.

Stake:
- simple: se mapea la Opportunity a un ValueOpportunity con su
  kelly_fraction_suggested persistido y FractionalKellyRiskManager aplica la
  fraccion y los limites.
- compound: la Kelly completa, la probabilidad y la cuota combinadas se toman
  de decision_metadata["compound"] (calculadas por DecisionEngine); aqui no se
  recalcula nada. Dependencia: la Recommendation debe traer esa metadata.

Idempotencia: Bet.recommendation_id es UNIQUE. Se consulta primero (caso
normal) y la constraint de la BD es la garantia definitiva ante concurrencia:
la insercion se hace en un SAVEPOINT; si salta IntegrityError se descarta
solo el savepoint y se devuelve el Bet ganador.

Limitacion: no hay feed de cuotas en vivo, asi que NO se valida cambio de
cuota; se congela Opportunity.odds_value tal como esta al ejecutar.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bets.bet_service import BetService
from app.db.models import Bet, Opportunity, Recommendation
from app.db.repositories.bet_repository import BetLegInput, BetRepository
from app.db.repositories.recommendation_repository import RecommendationRepository
from app.domain.interfaces import RiskManager
from app.domain.models import ValueOpportunity

_EXECUTABLE_OPPORTUNITY_STATUS = "candidate"
_EXECUTABLE_EVENT_STATUS = "scheduled"
_COMPOUND_METADATA_KEYS = ("probability", "odds", "expected_value", "kelly_full", "opportunity_ids")


class RecommendationNotFoundError(Exception):
    pass


class RecommendationNotExecutableError(Exception):
    pass


@dataclass(frozen=True)
class TrialExecution:
    recommendation_id: int
    bet: Bet | None  # None solo para 'no_bet'
    created: bool  # False si el Bet ya existia (idempotencia) o si fue no_bet
    reason: str | None = None  # motivo de no ejecucion ('no_bet')


class TrialExecutor:
    def __init__(self, db: Session, risk_manager: RiskManager):
        self._db = db
        self._risk_manager = risk_manager
        self._bet_repository = BetRepository(db)
        self._recommendation_repository = RecommendationRepository(db)
        self._bet_service = BetService(self._bet_repository, self._recommendation_repository)

    def execute(self, recommendation_id: int, placed_at: datetime) -> TrialExecution:
        recommendation = self._recommendation_repository.get(recommendation_id)
        if recommendation is None:
            raise RecommendationNotFoundError(f"Recommendation {recommendation_id} no existe")

        if recommendation.bet_type == "no_bet":
            return TrialExecution(recommendation_id, None, False, reason="no_bet")
        if recommendation.mode != "trial":
            raise RecommendationNotExecutableError(
                f"Recommendation {recommendation_id} tiene mode={recommendation.mode!r}; "
                "TrialExecutor solo ejecuta mode='trial'"
            )

        existing = self._bet_repository.get_by_recommendation(recommendation_id)
        if existing is not None:
            return TrialExecution(recommendation_id, existing, False)

        opportunities = self._load_opportunities(recommendation)
        self._validate_opportunities(opportunities, placed_at)
        stake = self._compute_stake(recommendation, opportunities)
        legs = [self._leg_input(o) for o in opportunities]

        try:
            with self._db.begin_nested():
                bet = self._bet_service.create_bet(
                    bet_type=recommendation.bet_type,
                    mode="trial",
                    stake=stake,
                    bankroll_at_time=float(recommendation.bankroll_at_recommendation),
                    placed_at=placed_at,
                    legs=legs,
                    recommendation_id=recommendation.id,
                )
        except IntegrityError:
            # Carrera: otro proceso creo el Bet entre la consulta y el insert.
            winner = self._bet_repository.get_by_recommendation(recommendation_id)
            if winner is None:
                raise  # IntegrityError distinto (p.ej. FK): error tecnico
            return TrialExecution(recommendation_id, winner, False)

        return TrialExecution(recommendation_id, bet, True)

    @staticmethod
    def _load_opportunities(recommendation: Recommendation) -> list[Opportunity]:
        legs = sorted(recommendation.legs, key=lambda leg: leg.leg_order)
        if not legs or (recommendation.bet_type == "simple" and len(legs) != 1):
            raise RecommendationNotExecutableError(
                f"Recommendation {recommendation.id} ({recommendation.bet_type}) "
                f"tiene {len(legs)} legs, cantidad inconsistente"
            )
        opportunities = []
        for leg in legs:
            if leg.opportunity is None:
                raise RecommendationNotExecutableError(
                    f"Opportunity {leg.opportunity_id} de la Recommendation {recommendation.id} no existe"
                )
            opportunities.append(leg.opportunity)
        return opportunities

    @staticmethod
    def _validate_opportunities(opportunities: list[Opportunity], placed_at: datetime) -> None:
        event_ids = [o.event_id for o in opportunities]
        if len(set(event_ids)) != len(event_ids):
            raise RecommendationNotExecutableError("La recomendacion repite event_id entre sus legs")

        now = _as_utc(placed_at)
        for o in opportunities:
            if o.status != _EXECUTABLE_OPPORTUNITY_STATUS:
                raise RecommendationNotExecutableError(
                    f"Opportunity {o.id} no es ejecutable (status={o.status!r})"
                )
            event = o.event
            if event is None or event.status != _EXECUTABLE_EVENT_STATUS:
                status = None if event is None else event.status
                raise RecommendationNotExecutableError(
                    f"Evento de la Opportunity {o.id} no es ejecutable (status={status!r})"
                )
            if _as_utc(event.start_time) <= now:
                raise RecommendationNotExecutableError(
                    f"Evento {event.id} de la Opportunity {o.id} ya comenzo (start_time <= placed_at)"
                )

    def _compute_stake(self, recommendation: Recommendation, opportunities: list[Opportunity]) -> float:
        if recommendation.bet_type == "simple":
            value_opportunity = self._simple_value_opportunity(opportunities[0])
        else:
            value_opportunity = self._compound_value_opportunity(recommendation, opportunities)

        stake = round(
            self._risk_manager.suggest_stake(
                value_opportunity, float(recommendation.bankroll_at_recommendation)
            ),
            2,
        )
        if stake <= 0:
            raise RecommendationNotExecutableError(
                f"RiskManager devolvio stake {stake} para la Recommendation {recommendation.id}"
            )
        return stake

    @staticmethod
    def _simple_value_opportunity(o: Opportunity) -> ValueOpportunity:
        return ValueOpportunity(
            event_external_id=str(o.event_id),
            market_type=o.market_type,
            selection=o.selection,
            bookmaker=o.bookmaker,
            odds_value=float(o.odds_value),
            estimated_probability=float(o.estimated_probability),
            implied_probability=float(o.implied_probability),
            edge=float(o.edge),
            expected_value=float(o.expected_value),
            kelly_fraction_suggested=float(o.kelly_fraction_suggested),
        )

    @staticmethod
    def _compound_value_opportunity(
        recommendation: Recommendation, opportunities: list[Opportunity]
    ) -> ValueOpportunity:
        """Representa la combinada como una sola propuesta usando los datos ya
        calculados por DecisionEngine (decision_metadata['compound'])."""
        data = (recommendation.decision_metadata or {}).get("compound")
        if not isinstance(data, dict) or any(k not in data for k in _COMPOUND_METADATA_KEYS):
            raise RecommendationNotExecutableError(
                f"Recommendation {recommendation.id} no trae decision_metadata['compound'] "
                "completo para calcular el stake"
            )
        if set(data["opportunity_ids"]) != {o.id for o in opportunities}:
            raise RecommendationNotExecutableError(
                f"decision_metadata['compound'] de la Recommendation {recommendation.id} "
                "no coincide con sus Opportunities"
            )
        probability = float(data["probability"])
        odds = float(data["odds"])
        implied = 1.0 / odds
        return ValueOpportunity(
            event_external_id="compound:" + ",".join(str(o.event_id) for o in opportunities),
            market_type="compound",
            selection="compound",
            bookmaker="compound",
            odds_value=odds,
            estimated_probability=probability,
            implied_probability=implied,
            edge=probability - implied,
            expected_value=float(data["expected_value"]),
            kelly_fraction_suggested=float(data["kelly_full"]),
        )

    @staticmethod
    def _leg_input(o: Opportunity) -> BetLegInput:
        return BetLegInput(
            event_id=o.event_id,
            market_type=o.market_type,
            selection=o.selection,
            bookmaker=o.bookmaker,
            odds_taken=float(o.odds_value),
        )


def _as_utc(value: datetime) -> datetime:
    """MySQL y SQLite devuelven datetimes naive; se asume UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
