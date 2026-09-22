from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Recommendation, RecommendationOpportunity


class RecommendationRepository:
    def __init__(self, db: Session):
        self._db = db

    def create(
        self,
        *,
        strategy_name: str,
        strategy_params: dict,
        bet_type: str,
        bankroll_at_recommendation: float,
        generated_at: datetime,
        opportunity_ids: list[int],
        explanation: str | None = None,
    ) -> Recommendation:
        """Crea la Recommendation junto con sus RecommendationOpportunity en
        una sola operacion atomica: si algo falla (p.ej. una opportunity_id
        invalida), no debe quedar una Recommendation sin sus legs."""
        recommendation = Recommendation(
            strategy_name=strategy_name,
            strategy_params=strategy_params,
            explanation=explanation,
            bet_type=bet_type,
            bankroll_at_recommendation=bankroll_at_recommendation,
            generated_at=generated_at,
        )
        self._db.add(recommendation)
        self._db.flush()

        for leg_order, opportunity_id in enumerate(opportunity_ids, start=1):
            self._db.add(
                RecommendationOpportunity(
                    recommendation_id=recommendation.id,
                    opportunity_id=opportunity_id,
                    leg_order=leg_order,
                )
            )
        self._db.flush()
        return recommendation

    def get(self, recommendation_id: int) -> Recommendation | None:
        return self._db.get(Recommendation, recommendation_id)
