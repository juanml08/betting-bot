"""Construye y persiste una Recommendation ya decidida por la capa superior.

Este servicio NO decide que estrategia usar ni compara simple vs compound:
solo valida la forma de la seleccion recibida (cantidad de Opportunities
segun bet_type, sin repetidas) y la persiste como snapshot inmutable via
RecommendationRepository.
"""

from datetime import datetime

from app.db.models import Recommendation
from app.db.repositories.recommendation_repository import RecommendationRepository

_COMPOUND_MIN_LEGS = 2
_COMPOUND_MAX_LEGS = 3


class RecommendationService:
    def __init__(self, repository: RecommendationRepository):
        self._repository = repository

    def create_recommendation(
        self,
        *,
        strategy_name: str,
        strategy_params: dict,
        bet_type: str,
        bankroll_at_recommendation: float,
        opportunity_ids: list[int],
        generated_at: datetime,
        explanation: str | None = None,
    ) -> Recommendation:
        self._validate_opportunity_ids(bet_type, opportunity_ids)

        return self._repository.create(
            strategy_name=strategy_name,
            strategy_params=strategy_params,
            bet_type=bet_type,
            bankroll_at_recommendation=bankroll_at_recommendation,
            generated_at=generated_at,
            opportunity_ids=opportunity_ids,
            explanation=explanation,
        )

    @staticmethod
    def _validate_opportunity_ids(bet_type: str, opportunity_ids: list[int]) -> None:
        if bet_type == "simple":
            if len(opportunity_ids) != 1:
                raise ValueError(
                    "Una Recommendation 'simple' debe tener exactamente 1 Opportunity, "
                    f"se recibieron {len(opportunity_ids)}"
                )
        elif bet_type == "compound":
            if not (_COMPOUND_MIN_LEGS <= len(opportunity_ids) <= _COMPOUND_MAX_LEGS):
                raise ValueError(
                    "Una Recommendation 'compound' debe tener entre "
                    f"{_COMPOUND_MIN_LEGS} y {_COMPOUND_MAX_LEGS} Opportunities, "
                    f"se recibieron {len(opportunity_ids)}"
                )
        else:
            raise ValueError(f"bet_type invalido: {bet_type!r} (esperado 'simple' o 'compound')")

        if len(set(opportunity_ids)) != len(opportunity_ids):
            raise ValueError("Una Recommendation no puede repetir la misma Opportunity")
