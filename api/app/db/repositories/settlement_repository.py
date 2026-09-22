from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Settlement


class SettlementRepository:
    def __init__(self, db: Session):
        self._db = db

    def get_by_bet(self, bet_id: int) -> Settlement | None:
        return self._db.query(Settlement).filter_by(bet_id=bet_id).one_or_none()

    def create(
        self,
        *,
        bet_id: int,
        settled_at: datetime,
        status: str,
        payout: float | None,
        profit_loss: float | None,
        notes: str | None = None,
    ) -> Settlement:
        settlement = Settlement(
            bet_id=bet_id,
            settled_at=settled_at,
            status=status,
            payout=payout,
            profit_loss=profit_loss,
            notes=notes,
        )
        self._db.add(settlement)
        self._db.flush()
        return settlement
