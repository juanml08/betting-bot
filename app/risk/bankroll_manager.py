"""Estado agregado de la banca, a partir del historial de movimientos.

Se mantiene independiente de la capa de persistencia (app.db) para poder
testearlo sin base de datos: recibe una lista simple de movimientos
(fecha, importe) y calcula balance actual y exposicion ya comprometida
en un dia dado.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BankrollMovement:
    occurred_on: date
    amount: float  # positivo: deposito/ganancia, negativo: stake/perdida


class BankrollManager:
    def __init__(self, initial_bankroll: float, movements: list[BankrollMovement] | None = None):
        self._initial_bankroll = initial_bankroll
        self._movements = movements or []

    @property
    def current_balance(self) -> float:
        return self._initial_bankroll + sum(m.amount for m in self._movements)

    def exposure_on(self, day: date) -> float:
        """Suma de stakes (importes negativos) comprometidos en un dia dado."""
        return -sum(m.amount for m in self._movements if m.occurred_on == day and m.amount < 0)

    def remaining_daily_capacity(self, day: date, max_daily_exposure_pct: float) -> float:
        max_exposure = self.current_balance * max_daily_exposure_pct
        already_committed = self.exposure_on(day)
        return max(max_exposure - already_committed, 0.0)
