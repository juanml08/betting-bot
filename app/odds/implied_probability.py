"""Etapa PROBABILIDAD IMPLICITA.

Convierte una cuota decimal en probabilidad implicita, y permite quitar el
margen de la casa (overround) cuando se conocen todas las cuotas de un
mercado, para no penalizar el edge por el margen del bookmaker.
"""

from app.domain.models import OddsQuote


def raw_implied_probability(odds_value: float) -> float:
    if odds_value <= 1.0:
        raise ValueError("odds_value debe ser mayor que 1.0")
    return 1.0 / odds_value


def overround(quotes: list[OddsQuote]) -> float:
    """Suma de probabilidades implicitas de todas las selecciones de un mercado.

    Un valor > 1.0 indica el margen que se lleva la casa de apuestas.
    """
    return sum(raw_implied_probability(q.odds_value) for q in quotes)


def fair_implied_probability(quote: OddsQuote, market_quotes: list[OddsQuote]) -> float:
    """Probabilidad implicita normalizada (sin margen) para una seleccion.

    `market_quotes` debe incluir todas las cuotas del mismo evento+mercado+
    bookmaker (todas las selecciones), para poder calcular y quitar el overround.
    """
    margin = overround(market_quotes)
    if margin <= 0:
        raise ValueError("El overround del mercado debe ser positivo")
    return raw_implied_probability(quote.odds_value) / margin
