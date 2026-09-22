from datetime import date

from pydantic import BaseModel, ConfigDict


class BankrollStatus(BaseModel):
    current_balance: float
    initial_bankroll: float


class BankrollTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_on: date
    amount: float
    reason: str
    balance_after: float
