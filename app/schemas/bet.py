from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BetCreate(BaseModel):
    """Registro manual de una apuesta que el usuario ya realizo fuera del sistema."""

    event_id: int
    market_type: str
    selection: str
    odds_taken: float = Field(gt=1.0)
    stake: float = Field(gt=0.0)
    opportunity_id: int | None = None
    notes: str | None = None


class BetSettle(BaseModel):
    status: str = Field(pattern="^(won|lost|void|pushed)$")


class BetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    opportunity_id: int | None
    event_id: int
    market_type: str
    selection: str
    odds_taken: float
    stake: float
    bankroll_at_time: float
    placed_at: datetime
    status: str
    settled_at: datetime | None
    notes: str | None
