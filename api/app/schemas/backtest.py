from datetime import date, datetime

from pydantic import BaseModel


class BacktestRequest(BaseModel):
    date_from: date
    date_to: date


class BacktestResult(BaseModel):
    strategy_name: str
    date_from: date
    date_to: date
    num_bets: int
    roi: float
    win_rate: float
    brier_score: float
    max_drawdown: float
    created_at: datetime
