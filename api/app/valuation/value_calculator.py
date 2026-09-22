"""Etapa VALUE / EDGE.

Compara la probabilidad estimada por el modelo contra la probabilidad
implicita de una cuota de mercado (ya sin el margen de la casa) y calcula:

- edge: diferencia entre probabilidad estimada e implicita.
- expected_value (EV): valor esperado por unidad de stake.
- kelly_fraction_suggested: fraccion de Kelly *completa* (sin aplicar todavia
  el Kelly fraccional de gestion de riesgo, que se aplica despues en
  app.risk.bankroll).

Esto NO es una recomendacion de apuesta por si sola: son solo numeros que
alimentan los filtros y la gestion de riesgo.
"""

from app.domain.models import OddsQuote, ProbabilityEstimate, ValueOpportunity
from app.odds.implied_probability import fair_implied_probability


class ValueCalculator:
    def calculate(
        self,
        estimate: ProbabilityEstimate,
        quote: OddsQuote,
        market_quotes: list[OddsQuote] | None = None,
    ) -> ValueOpportunity:
        market_quotes = market_quotes or [quote]
        implied_probability = fair_implied_probability(quote, market_quotes)

        p = estimate.probability
        edge = p - implied_probability

        b = quote.odds_value - 1.0
        expected_value = p * b - (1.0 - p)

        kelly_fraction = (b * p - (1.0 - p)) / b if b > 0 else 0.0
        kelly_fraction_suggested = max(kelly_fraction, 0.0)

        return ValueOpportunity(
            event_external_id=estimate.event_external_id,
            market_type=estimate.market_type,
            selection=estimate.selection,
            bookmaker=quote.bookmaker,
            odds_value=quote.odds_value,
            estimated_probability=p,
            implied_probability=implied_probability,
            edge=edge,
            expected_value=expected_value,
            kelly_fraction_suggested=kelly_fraction_suggested,
        )
