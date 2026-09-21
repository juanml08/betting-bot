from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Bet


class BetRepository:
    def __init__(self, db: Session):
        self._db = db

    def list_bets(self, *, status: str | None = None) -> list[Bet]:
        stmt = select(Bet)
        if status:
            stmt = stmt.where(Bet.status == status)
        return list(self._db.scalars(stmt.order_by(Bet.placed_at.desc())))

    def get(self, bet_id: int) -> Bet | None:
        return self._db.get(Bet, bet_id)

    def create(
        self,
        *,
        event_id: int,
        market_type: str,
        selection: str,
        odds_taken: float,
        stake: float,
        bankroll_at_time: float,
        placed_at: datetime,
        opportunity_id: int | None = None,
        notes: str | None = None,
    ) -> Bet:
        bet = Bet(
            opportunity_id=opportunity_id,
            event_id=event_id,
            market_type=market_type,
            selection=selection,
            odds_taken=odds_taken,
            stake=stake,
            bankroll_at_time=bankroll_at_time,
            placed_at=placed_at,
            status="pending",
            notes=notes,
        )
        self._db.add(bet)
        self._db.flush()
        return bet

    def settle(self, bet_id: int, *, status: str, settled_at: datetime) -> Bet | None:
        bet = self.get(bet_id)
        if bet is None:
            return None
        bet.status = status
        bet.settled_at = settled_at
        self._db.flush()
        return bet
