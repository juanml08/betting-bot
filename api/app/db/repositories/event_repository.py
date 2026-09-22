from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Event


class EventRepository:
    def __init__(self, db: Session):
        self._db = db

    def list_events(self, *, sport: str | None = None) -> list[Event]:
        stmt = select(Event)
        if sport:
            stmt = stmt.where(Event.sport == sport)
        return list(self._db.scalars(stmt.order_by(Event.start_time)))

    def get_by_external_id(self, external_id: str) -> Event | None:
        stmt = select(Event).where(Event.external_id == external_id)
        return self._db.scalars(stmt).first()
