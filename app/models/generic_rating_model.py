"""Modelo baseline generico tipo Elo, valido para cualquier deporte con
enfrentamiento directo entre dos competidores (con o sin posibilidad de empate).

No es especifico de futbol, baloncesto o tenis: solo usa los ratings
calculados en app.features.feature_builder y una probabilidad de empate fija
y configurable para deportes donde el empate existe. Es intencionalmente
simple: sirve como punto de partida reemplazable, no como modelo definitivo.
"""

from datetime import datetime, timezone

from app.domain.models import MatchEvent, ProbabilityEstimate

DEFAULT_DRAW_PROBABILITY = 0.25


class GenericRatingModel:
    name = "generic_rating_elo"
    version = "0.1.0"

    def __init__(self, draw_probability: float = DEFAULT_DRAW_PROBABILITY):
        self._draw_probability = draw_probability

    def estimate(
        self, event: MatchEvent, market_type: str, features: dict
    ) -> list[ProbabilityEstimate]:
        rating_home = features["rating_home"]
        rating_away = features["rating_away"]
        allows_draw = features.get("allows_draw", False)

        expected_home = 1.0 / (1.0 + 10 ** ((rating_away - rating_home) / 400.0))
        now = datetime.now(timezone.utc)

        def make(selection: str, probability: float) -> ProbabilityEstimate:
            return ProbabilityEstimate(
                event_external_id=event.external_id,
                market_type=market_type,
                selection=selection,
                model_name=self.name,
                model_version=self.version,
                probability=probability,
                computed_at=now,
            )

        if allows_draw:
            draw_prob = self._draw_probability
            remaining = 1.0 - draw_prob
            home_prob = remaining * expected_home
            away_prob = remaining * (1.0 - expected_home)
            return [
                make("home", home_prob),
                make("draw", draw_prob),
                make("away", away_prob),
            ]

        return [
            make("home", expected_home),
            make("away", 1.0 - expected_home),
        ]
