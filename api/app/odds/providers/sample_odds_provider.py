"""Proveedor de cuotas de ejemplo: lee cuotas desde un CSV local.

Igual que SampleDataProvider, es solo una implementacion de referencia del
Protocol OddsProvider. El sistema nunca usa esto para ejecutar apuestas,
solo para leer cuotas y compararlas contra la probabilidad estimada.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from app.domain.models import OddsQuote

DEFAULT_FIXTURE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sample_odds.csv"


class SampleOddsProvider:
    def __init__(self, csv_path: Path | str = DEFAULT_FIXTURE_PATH):
        self._csv_path = Path(csv_path)

    def get_odds(self, event_external_id: str) -> list[OddsQuote]:
        df = pd.read_csv(self._csv_path, dtype=str)
        rows = df[df["event_external_id"] == event_external_id]
        return [
            OddsQuote(
                event_external_id=row.event_external_id,
                market_type=row.market_type,
                selection=row.selection,
                bookmaker=row.bookmaker,
                odds_value=float(row.odds_value),
                captured_at=datetime.fromisoformat(row.captured_at),
            )
            for row in rows.itertuples(index=False)
        ]
