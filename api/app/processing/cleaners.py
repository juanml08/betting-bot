"""Etapa PROCESAMIENTO: normalizacion/limpieza de eventos ya convertidos a MatchEvent.

Los DataProvider concretos son responsables de convertir su formato crudo
(JSON de una API, filas de un CSV, etc.) a MatchEvent. Esta etapa se encarga
de limpiezas transversales que aplican sin importar la fuente: eliminar
duplicados, normalizar nombres y ordenar cronologicamente.
"""

from app.domain.models import MatchEvent


def normalize_team_name(name: str) -> str:
    return " ".join(name.strip().split())


def dedupe_events(events: list[MatchEvent]) -> list[MatchEvent]:
    seen: set[str] = set()
    unique: list[MatchEvent] = []
    for event in events:
        if event.external_id in seen:
            continue
        seen.add(event.external_id)
        unique.append(event)
    return unique


def clean_events(events: list[MatchEvent]) -> list[MatchEvent]:
    cleaned = [
        MatchEvent(
            external_id=e.external_id,
            sport=e.sport,
            league=e.league,
            competitor_home=normalize_team_name(e.competitor_home),
            competitor_away=normalize_team_name(e.competitor_away),
            start_time=e.start_time,
            status=e.status,
            source=e.source,
            result=e.result,
        )
        for e in events
    ]
    return sorted(dedupe_events(cleaned), key=lambda e: e.start_time)
