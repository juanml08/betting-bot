"""Metricas puras para una propuesta binaria (probabilidad p, cuota decimal o).

Precondicion (la valida quien llama): 0 < p < 1, o > 1, valores finitos.

- expected_value: EV = p * o - 1.
- kelly_full: f* = EV / (o - 1). Fraccion de Kelly *completa*, sin recortes.
- log_growth: G* = crecimiento logaritmico esperado por apuesta al apostar
  f*: p * ln(p * o) + (1 - p) * ln((1 - p) * o / (o - 1)).
  Se cumple G* > 0  <=>  EV > 0.
"""

import math


def expected_value(p: float, odds: float) -> float:
    return p * odds - 1.0


def kelly_full(p: float, odds: float) -> float:
    return expected_value(p, odds) / (odds - 1.0)


def log_growth(p: float, odds: float) -> float:
    return p * math.log(p * odds) + (1.0 - p) * math.log((1.0 - p) * odds / (odds - 1.0))
