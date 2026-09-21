"""Contratos (Protocols) para cada etapa del pipeline.

La idea es que cualquier etapa se pueda sustituir por otra implementacion
(un proveedor de datos real, un modelo de probabilidad mas sofisticado, una
politica de riesgo distinta) sin tener que tocar el resto del sistema: solo
hace falta que cumpla el Protocol correspondiente.
"""

from datetime import datetime
from typing import Protocol

from app.domain.models import MatchEvent, OddsQuote, ProbabilityEstimate, ValueOpportunity


class DataProvider(Protocol):
    """Etapa DATOS DEPORTIVOS: obtiene eventos crudos de una fuente."""

    def get_events(
        self, *, since: datetime | None = None, until: datetime | None = None
    ) -> list[MatchEvent]: ...


class OddsProvider(Protocol):
    """Etapa CUOTA: obtiene cuotas de mercado para eventos."""

    def get_odds(self, event_external_id: str) -> list[OddsQuote]: ...


class FeatureExtractor(Protocol):
    """Etapa ESTADISTICAS / FEATURES: construye features a partir de eventos historicos."""

    def build_features(self, event: MatchEvent, history: list[MatchEvent]) -> dict: ...


class ProbabilityModel(Protocol):
    """Etapa MODELO O ESTRATEGIA: produce una probabilidad estimada por seleccion."""

    name: str
    version: str

    def estimate(
        self, event: MatchEvent, market_type: str, features: dict
    ) -> list[ProbabilityEstimate]: ...


class ValueCalculator(Protocol):
    """Etapa VALUE / EDGE: compara probabilidad estimada vs. implicita de la cuota."""

    def calculate(
        self, estimate: ProbabilityEstimate, quote: OddsQuote
    ) -> ValueOpportunity: ...


class OpportunityFilter(Protocol):
    """Etapa FILTROS: decide si una oportunidad es lo bastante buena para pasar."""

    def passes(self, opportunity: ValueOpportunity) -> bool: ...


class RiskManager(Protocol):
    """Etapa GESTION DE RIESGO: calcula el stake recomendado dado el estado de banca."""

    def suggest_stake(self, opportunity: ValueOpportunity, current_bankroll: float) -> float: ...
