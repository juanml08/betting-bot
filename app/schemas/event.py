from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    sport: str
    league: str
    competitor_home: str
    competitor_away: str
    start_time: datetime
    status: str
    source: str
    result: str | None
