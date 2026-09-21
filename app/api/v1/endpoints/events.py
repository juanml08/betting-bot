from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.db.repositories.event_repository import EventRepository
from app.schemas.event import EventRead

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventRead])
def list_events(sport: str | None = None, db: Session = Depends(get_db)) -> list[EventRead]:
    events = EventRepository(db).list_events(sport=sport)
    return [EventRead.model_validate(e) for e in events]
