"""Valida la forma de un Bet antes de persistirlo (cantidad de BetLeg segun
bet_type, sin event_id repetidos, mode valido, recommendation_id existente)
y delega la persistencia en BetRepository.

No decide que apostar ni compara propuestas: eso es responsabilidad del
Decision Engine (fase futura). Este servicio solo garantiza que lo que se
le pide guardar tiene una forma valida, igual que RecommendationService hace
para Recommendation.

La unicidad de recommendation_id (una Recommendation origina como maximo un
Bet) NO se valida aqui de forma optimista: se deja que la constraint UNIQUE
de la base de datos la haga cumplir, para que sea correcta incluso bajo
concurrencia (dos intentos simultaneos de crear un Bet para la misma
Recommendation).
"""

from datetime import datetime

from app.db.models import Bet
from app.db.repositories.bet_repository import BetLegInput, BetRepository
from app.db.repositories.recommendation_repository import RecommendationRepository

_COMPOUND_MIN_LEGS = 2
_COMPOUND_MAX_LEGS = 3
_VALID_MODES = ("real", "trial")


class BetService:
    def __init__(self, bet_repository: BetRepository, recommendation_repository: RecommendationRepository):
        self._bet_repository = bet_repository
        self._recommendation_repository = recommendation_repository

    def create_bet(
        self,
        *,
        bet_type: str,
        mode: str,
        stake: float,
        bankroll_at_time: float,
        placed_at: datetime,
        legs: list[BetLegInput],
        recommendation_id: int | None = None,
        notes: str | None = None,
    ) -> Bet:
        self._validate_mode(mode)
        self._validate_legs(bet_type, legs)

        if recommendation_id is not None:
            if self._recommendation_repository.get(recommendation_id) is None:
                raise ValueError(f"Recommendation {recommendation_id} no existe")

        return self._bet_repository.create(
            bet_type=bet_type,
            mode=mode,
            stake=stake,
            bankroll_at_time=bankroll_at_time,
            placed_at=placed_at,
            legs=legs,
            recommendation_id=recommendation_id,
            notes=notes,
        )

    @staticmethod
    def _validate_mode(mode: str) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(f"mode invalido: {mode!r} (esperado 'real' o 'trial')")

    @staticmethod
    def _validate_legs(bet_type: str, legs: list[BetLegInput]) -> None:
        if bet_type == "simple":
            if len(legs) != 1:
                raise ValueError(
                    f"Un Bet 'simple' debe tener exactamente 1 BetLeg, se recibieron {len(legs)}"
                )
        elif bet_type == "compound":
            if not (_COMPOUND_MIN_LEGS <= len(legs) <= _COMPOUND_MAX_LEGS):
                raise ValueError(
                    "Un Bet 'compound' debe tener entre "
                    f"{_COMPOUND_MIN_LEGS} y {_COMPOUND_MAX_LEGS} BetLeg, se recibieron {len(legs)}"
                )
        else:
            raise ValueError(f"bet_type invalido: {bet_type!r} (esperado 'simple' o 'compound')")

        event_ids = [leg["event_id"] for leg in legs]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("Un Bet no puede tener dos BetLeg del mismo event_id")
