from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OpportunityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    market_type: str
    selection: str
    bookmaker: str
    odds_value: float
    estimated_probability: float
    implied_probability: float
    edge: float
    expected_value: float
    kelly_fraction_suggested: float
    suggested_stake: float
    status: str
    created_at: datetime
    version: int
    last_observed_at: datetime
    superseded_at: datetime | None = None
    superseded_by_id: int | None = None
