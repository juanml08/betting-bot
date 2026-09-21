"""Etapa GESTION DE RIESGO.

Convierte la fraccion de Kelly "completa" de una oportunidad en un stake
concreto, aplicando:

- Kelly fraccional (apostar solo una fraccion del Kelly completo, mas
  conservador y menos sensible a errores de estimacion de probabilidad).
- Un limite maximo de stake por apuesta como % de la banca.

La gestion de exposicion diaria (cuanto se puede arriesgar en total en un
dia) se aplica en bankroll_manager.py, que conoce el estado agregado de
la banca y no solo una oportunidad aislada.
"""

from dataclasses import dataclass

from app.domain.models import ValueOpportunity


@dataclass
class RiskConfig:
    kelly_fraction: float
    max_stake_pct_per_bet: float


class FractionalKellyRiskManager:
    def __init__(self, config: RiskConfig):
        self._config = config

    def suggest_stake(self, opportunity: ValueOpportunity, current_bankroll: float) -> float:
        if current_bankroll <= 0:
            return 0.0

        fractional_kelly = opportunity.kelly_fraction_suggested * self._config.kelly_fraction
        capped_fraction = min(fractional_kelly, self._config.max_stake_pct_per_bet)
        return max(capped_fraction, 0.0) * current_bankroll
