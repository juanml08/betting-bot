"""Identidad de un slot de Opportunity: (event, market_type, selection, bookmaker).

Unica definicion de la normalizacion, compartida por el pipeline
(OpportunityService) y la persistencia (OpportunityLifecycleService) para que
ambos manejen la misma identidad. Solo se normalizan espacios y casing; no se
altera el significado de la seleccion.
"""

from dataclasses import dataclass
from datetime import datetime, timezone


def normalize_slot_text(value: str) -> str:
    return value.strip().lower()


def to_naive_utc(value: datetime) -> datetime:
    """La BD guarda datetimes naive en UTC (mismo criterio que TrialService)."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class SlotKey:
    """Identidad normalizada de un slot; event_ref es external_id o id interno."""

    event_ref: str | int
    market_type: str
    selection: str
    bookmaker: str

    @classmethod
    def of(cls, event_ref: str | int, market_type: str, selection: str, bookmaker: str) -> "SlotKey":
        return cls(
            event_ref,
            normalize_slot_text(market_type),
            normalize_slot_text(selection),
            normalize_slot_text(bookmaker),
        )
