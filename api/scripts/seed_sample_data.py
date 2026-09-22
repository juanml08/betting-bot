"""Carga los eventos y cuotas de muestra (tests/fixtures) en la base de datos.

Uso: poetry run python scripts/seed_sample_data.py
"""

from app.core.database import SessionLocal
from app.db.models import Event, MarketOdds
from app.ingestion.providers.sample_data_provider import SampleDataProvider
from app.odds.providers.sample_odds_provider import SampleOddsProvider
from app.processing.cleaners import clean_events


def main() -> None:
    events = clean_events(SampleDataProvider().get_events())
    odds_provider = SampleOddsProvider()

    db = SessionLocal()
    try:
        created, skipped = 0, 0
        for event in events:
            existing = db.query(Event).filter_by(external_id=event.external_id).one_or_none()
            if existing is not None:
                skipped += 1
                continue

            record = Event(
                external_id=event.external_id,
                sport=event.sport,
                league=event.league,
                competitor_home=event.competitor_home,
                competitor_away=event.competitor_away,
                start_time=event.start_time,
                status=event.status.value,
                source=event.source,
                result=event.result,
            )
            db.add(record)
            db.flush()

            for quote in odds_provider.get_odds(event.external_id):
                db.add(
                    MarketOdds(
                        event_id=record.id,
                        market_type=quote.market_type,
                        selection=quote.selection,
                        bookmaker=quote.bookmaker,
                        odds_value=quote.odds_value,
                        captured_at=quote.captured_at,
                    )
                )
            created += 1

        db.commit()
        print(f"Eventos creados: {created}, ya existentes (omitidos): {skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
