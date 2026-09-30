"""Proveedor de EventUpdate en memoria: para tests y pruebas locales sin Internet.

Cumple el Protocol EventUpdateProvider. Devuelve siempre todas las
actualizaciones configuradas (un proveedor real puede repetirlas: la ingesta
es idempotente).
"""

from datetime import datetime

from app.domain.models import EventUpdate


class InMemoryEventUpdateProvider:
    def __init__(self, updates: list[EventUpdate] | None = None):
        self._updates = list(updates or [])

    def set_updates(self, updates: list[EventUpdate]) -> None:
        self._updates = list(updates)

    def push(self, external_id: str, status: str, result: str | None = None) -> None:
        self._updates.append(EventUpdate(external_id=external_id, status=status, result=result))

    def get_event_updates(self, *, since: datetime | None = None) -> list[EventUpdate]:
        return list(self._updates)
