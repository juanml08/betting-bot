"""Proveedor de datos de ejemplo: lee eventos desde un CSV local.

Sirve como implementacion de referencia del Protocol DataProvider. Para
conectar una fuente real (API-Football, The Odds API, etc.) basta con
escribir otra clase que cumpla el mismo Protocol y usarla en su lugar.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from app.domain.models import EventStatus, MatchEvent

DEFAULT_FIXTURE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sample_events.csv"


class SampleDataProvider:
    def __init__(self, csv_path: Path | str = DEFAULT_FIXTURE_PATH):
        self._csv_path = Path(csv_path)

    def get_events(
        self, *, since: datetime | None = None, until: datetime | None = None
    ) -> list[MatchEvent]:
        df = pd.read_csv(self._csv_path, dtype=str, keep_default_na=False)
        events: list[MatchEvent] = []
        for row in df.itertuples(index=False):
            start_time = datetime.fromisoformat(row.start_time)
            if since is not None and start_time < since:
                continue
            if until is not None and start_time > until:
                continue
            events.append(
                MatchEvent(
                    external_id=row.external_id,
                    sport=row.sport,
                    league=row.league,
                    competitor_home=row.competitor_home,
                    competitor_away=row.competitor_away,
                    start_time=start_time,
                    status=EventStatus(row.status),
                    source=row.source,
                    result=row.result or None,
                )
            )
        return sorted(events, key=lambda e: e.start_time)
