"""Etapa ESTADISTICAS / FEATURES.

Construye, para un evento dado, las features que el modelo de probabilidad
necesita. El baseline actual (generic_rating_model) solo necesita ratings
tipo Elo de ambos competidores y si el mercado admite empate, pero esta
funcion es el punto donde se anadirian features mas ricas en el futuro
(forma reciente, lesiones, local/visitante, superficie, etc.) sin tener que
tocar el modelo en si.
"""

from app.domain.models import MatchEvent

DEFAULT_RATING = 1500.0
K_FACTOR = 30.0


def compute_ratings(history: list[MatchEvent], default_rating: float = DEFAULT_RATING) -> dict[str, float]:
    """Calcula ratings Elo a partir de eventos finalizados, en orden cronologico.

    `history` debe contener unicamente eventos anteriores al que se quiere
    predecir (el llamador es responsable de filtrar por fecha) para evitar
    look-ahead bias.
    """
    ratings: dict[str, float] = {}

    def get(name: str) -> float:
        return ratings.get(name, default_rating)

    for event in sorted(history, key=lambda e: e.start_time):
        if event.status != "finished" or event.result is None:
            continue
        home, away = event.competitor_home, event.competitor_away
        r_home, r_away = get(home), get(away)
        expected_home = 1.0 / (1.0 + 10 ** ((r_away - r_home) / 400.0))

        if event.result == "home_win":
            score_home = 1.0
        elif event.result == "away_win":
            score_home = 0.0
        else:  # draw
            score_home = 0.5

        ratings[home] = r_home + K_FACTOR * (score_home - expected_home)
        ratings[away] = r_away + K_FACTOR * ((1.0 - score_home) - (1.0 - expected_home))

    return ratings


def sport_allows_draw(sport: str, history: list[MatchEvent]) -> bool:
    return any(e.sport == sport and e.result == "draw" for e in history)


def build_features(event: MatchEvent, history: list[MatchEvent]) -> dict:
    prior_events = [
        e for e in history if e.sport == event.sport and e.start_time < event.start_time
    ]
    ratings = compute_ratings(prior_events)

    return {
        "rating_home": ratings.get(event.competitor_home, DEFAULT_RATING),
        "rating_away": ratings.get(event.competitor_away, DEFAULT_RATING),
        "allows_draw": sport_allows_draw(event.sport, prior_events),
    }
