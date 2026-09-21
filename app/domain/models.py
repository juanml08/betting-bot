"""Objetos de dominio puros (sin dependencias de FastAPI/SQLAlchemy).

Estas clases son las que fluyen entre las etapas del pipeline:
datos -> features -> modelo -> probabilidad -> cuota -> value -> oportunidad.
Los modelos ORM en app/db/models.py son la representacion persistida de
un subconjunto de estos objetos.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class EventStatus(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class MatchEvent:
    """Un evento deportivo entre dos competidores (equipo, jugador, etc.)."""

    external_id: str
    sport: str
    league: str
    competitor_home: str
    competitor_away: str
    start_time: datetime
    status: EventStatus
    source: str
    result: str | None = None  # p.ej. "home_win", "away_win", "draw" una vez finalizado


@dataclass(frozen=True)
class OddsQuote:
    """Una cuota de mercado para una seleccion concreta de un evento."""

    event_external_id: str
    market_type: str  # p.ej. "1x2", "moneyline", "over_under_2_5"
    selection: str  # p.ej. "home", "away", "draw", "over"
    bookmaker: str
    odds_value: float
    captured_at: datetime


@dataclass(frozen=True)
class ProbabilityEstimate:
    """Probabilidad estimada por un modelo para una seleccion de un evento."""

    event_external_id: str
    market_type: str
    selection: str
    model_name: str
    model_version: str
    probability: float
    computed_at: datetime


@dataclass(frozen=True)
class ValueOpportunity:
    """Resultado de comparar una probabilidad estimada contra una cuota de mercado."""

    event_external_id: str
    market_type: str
    selection: str
    bookmaker: str
    odds_value: float
    estimated_probability: float
    implied_probability: float
    edge: float
    expected_value: float
    kelly_fraction_suggested: float
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)
