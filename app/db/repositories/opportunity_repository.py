from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Opportunity
from app.opportunities.opportunity_service import OpportunityCandidate


class OpportunityRepository:
    def __init__(self, db: Session):
        self._db = db

    def list_candidates(self, *, status: str | None = None) -> list[Opportunity]:
        stmt = select(Opportunity)
        if status:
            stmt = stmt.where(Opportunity.status == status)
        return list(self._db.scalars(stmt.order_by(Opportunity.created_at.desc())))

    def save_candidate(self, candidate: OpportunityCandidate, event_id: int) -> Opportunity:
        opp = candidate.opportunity
        record = Opportunity(
            event_id=event_id,
            market_type=opp.market_type,
            selection=opp.selection,
            bookmaker=opp.bookmaker,
            odds_value=opp.odds_value,
            estimated_probability=opp.estimated_probability,
            implied_probability=opp.implied_probability,
            edge=opp.edge,
            expected_value=opp.expected_value,
            kelly_fraction_suggested=opp.kelly_fraction_suggested,
            suggested_stake=candidate.suggested_stake,
            status="candidate",
            created_at=datetime.now(timezone.utc),
        )
        self._db.add(record)
        self._db.flush()
        return record
