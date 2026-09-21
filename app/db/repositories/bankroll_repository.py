from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BankrollTransaction


class BankrollRepository:
    def __init__(self, db: Session):
        self._db = db

    def list_transactions(self) -> list[BankrollTransaction]:
        stmt = select(BankrollTransaction).order_by(BankrollTransaction.occurred_on)
        return list(self._db.scalars(stmt))

    def current_balance(self, initial_bankroll: float) -> float:
        transactions = self.list_transactions()
        return initial_bankroll + sum(float(t.amount) for t in transactions)

    def record(
        self,
        *,
        occurred_on: date,
        amount: float,
        reason: str,
        balance_after: float,
        related_bet_id: int | None = None,
    ) -> BankrollTransaction:
        tx = BankrollTransaction(
            occurred_on=occurred_on,
            amount=amount,
            reason=reason,
            balance_after=balance_after,
            related_bet_id=related_bet_id,
        )
        self._db.add(tx)
        self._db.flush()
        return tx
