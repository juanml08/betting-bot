from datetime import datetime
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Bet, BetLeg


class BetLegInput(TypedDict):
    event_id: int
    market_type: str
    selection: str
    bookmaker: str
    odds_taken: float


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
        bet_type: str,
        mode: str,
        stake: float,
        bankroll_at_time: float,
        placed_at: datetime,
        legs: list[BetLegInput],
        recommendation_id: int | None = None,
        notes: str | None = None,
    ) -> Bet:
        """Crea el Bet junto con sus BetLeg en una sola operacion atomica: si
        algo falla (p.ej. un event_id invalido), no debe quedar un Bet sin
        sus legs. La validacion de forma (cantidad de legs segun bet_type,
        sin event_id repetidos) es responsabilidad de BetService, no de este
        repositorio."""
        bet = Bet(
            recommendation_id=recommendation_id,
            bet_type=bet_type,
            mode=mode,
            stake=stake,
            bankroll_at_time=bankroll_at_time,
            placed_at=placed_at,
            status="pending",
            notes=notes,
        )
        self._db.add(bet)
        self._db.flush()

        for leg_order, leg in enumerate(legs, start=1):
            self._db.add(
                BetLeg(
                    bet_id=bet.id,
                    leg_order=leg_order,
                    event_id=leg["event_id"],
                    market_type=leg["market_type"],
                    selection=leg["selection"],
                    bookmaker=leg["bookmaker"],
                    odds_taken=leg["odds_taken"],
                    result="pending",
                )
            )
        self._db.flush()
        return bet
