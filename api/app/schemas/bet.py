from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BetLegCreate(BaseModel):
    event_id: int
    market_type: str
    selection: str
    bookmaker: str
    odds_taken: float = Field(gt=1.0)


class BetCreate(BaseModel):
    """Registro de una apuesta ya colocada: manual (mode='real', el usuario ya
    aposto fuera del sistema) o, en el futuro, generada por TRIAL
    (mode='trial') con dinero ficticio. Este endpoint nunca ejecuta ni envia
    la apuesta a ningun lado, solo deja constancia."""

    bet_type: str = Field(pattern="^(simple|compound)$")
    mode: str = Field(default="real", pattern="^(real|trial)$")
    stake: float = Field(gt=0.0)
    legs: list[BetLegCreate] = Field(min_length=1)
    recommendation_id: int | None = None
    notes: str | None = None


class BetLegRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bet_id: int
    leg_order: int
    event_id: int
    market_type: str
    selection: str
    bookmaker: str
    odds_taken: float
    result: str


class SettlementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bet_id: int
    settled_at: datetime
    status: str
    payout: float | None
    profit_loss: float | None
    notes: str | None


class BetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recommendation_id: int | None
    bet_type: str
    mode: str
    stake: float
    bankroll_at_time: float
    placed_at: datetime
    status: str
    notes: str | None
    legs: list[BetLegRead]
    settlement: SettlementRead | None


class BetLegResult(BaseModel):
    leg_order: int
    result: str = Field(pattern="^(won|lost|void)$")


class BetSettle(BaseModel):
    leg_results: list[BetLegResult] = Field(min_length=1)
    notes: str | None = None
