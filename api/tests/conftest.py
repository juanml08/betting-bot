"""Fixtures compartidas para tests de API y persistencia.

No existia una estrategia de test-DB previa en el proyecto (ver reglas.md,
"no adelantar fases" / "no cambiar arquitectura"): se agrega aqui una base
SQLite en memoria, aislada por test, sin tocar la configuracion de
produccion (que sigue usando MySQL via app.core.database.settings).

Todos los modelos ORM usados (Numeric, JSON, ForeignKey, relationship) son
compatibles con SQLite a traves de SQLAlchemy, por lo que no hace falta
Docker ni un servidor MySQL real para estos tests.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_opportunity_filter, get_opportunity_service, get_risk_manager
from app.core.config import Settings, get_settings
from app.core.database import Base, get_db
from app.db.models import Event, MarketOdds
from app.ingestion.providers.sample_data_provider import SampleDataProvider
from app.main import app
from app.models.generic_rating_model import GenericRatingModel
from app.odds.providers.sample_odds_provider import SampleOddsProvider
from app.opportunities.opportunity_service import OpportunityService
from app.processing.cleaners import clean_events


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite no aplica FKs por defecto (a diferencia de MySQL/InnoDB en
    # produccion); se activa explicitamente para que los tests de
    # constraints de integridad referencial sean representativos.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def db_session(db_engine) -> Session:
    testing_session_local = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def test_settings() -> Settings:
    """Settings deterministas y aislados de produccion para tests de API."""
    return Settings(
        database_url="sqlite://",
        initial_bankroll=1000.0,
        kelly_fraction=0.25,
        max_stake_pct_per_bet=0.05,
        max_daily_exposure_pct=0.20,
        min_edge=0.03,
        min_expected_value=0.0,
        min_odds=1.3,
        max_odds=10.0,
    )


def _permissive_settings() -> Settings:
    """Filtros permisivos para generar candidatas/apuestas de forma
    deterministica a partir de los fixtures de muestra, sin depender del
    tuning de negocio configurado por defecto en Settings (que puede cambiar)."""
    return Settings(
        min_edge=-1.0,
        min_expected_value=-1.0,
        min_odds=1.0,
        max_odds=100.0,
        kelly_fraction=0.25,
        max_stake_pct_per_bet=0.05,
    )


def _permissive_opportunity_service() -> OpportunityService:
    permissive_settings = _permissive_settings()
    return OpportunityService(
        data_provider=SampleDataProvider(),
        odds_provider=SampleOddsProvider(),
        probability_model=GenericRatingModel(),
        opportunity_filter=get_opportunity_filter(permissive_settings),
        risk_manager=get_risk_manager(permissive_settings),
    )


@pytest.fixture()
def client(db_session, test_settings):
    """TestClient con la DB y los settings sobreescritos para aislar los tests."""

    def _get_db_override():
        yield db_session

    def _get_settings_override():
        return test_settings

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_settings] = _get_settings_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def client_permissive_backtest(client):
    """Variante del client con Settings permisivos (edge/EV/odds) para que el
    backtest genere apuestas simuladas de forma deterministica sobre los
    fixtures de muestra. El endpoint de backtest si respeta el override de
    get_settings (lo recibe por Depends), a diferencia de /opportunities/generate."""

    def _get_settings_override():
        return _permissive_settings()

    app.dependency_overrides[get_settings] = _get_settings_override
    yield client
    # La limpieza final de overrides la hace el fixture `client`.


@pytest.fixture()
def client_permissive_opportunities(client):
    """Variante del client que ademas fuerza un OpportunityService permisivo,
    porque get_opportunity_service construye sus propios Settings
    internamente y no respeta el override de get_settings."""
    app.dependency_overrides[get_opportunity_service] = _permissive_opportunity_service
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_opportunity_service, None)


@pytest.fixture()
def seeded_events(db_session) -> dict[str, Event]:
    """Carga los eventos y cuotas de muestra (mismos fixtures que
    scripts/seed_sample_data.py) en la DB de test."""
    events = clean_events(SampleDataProvider().get_events())
    odds_provider = SampleOddsProvider()

    created: dict[str, Event] = {}
    for event in events:
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
        db_session.add(record)
        db_session.flush()

        for quote in odds_provider.get_odds(event.external_id):
            db_session.add(
                MarketOdds(
                    event_id=record.id,
                    market_type=quote.market_type,
                    selection=quote.selection,
                    bookmaker=quote.bookmaker,
                    odds_value=quote.odds_value,
                    captured_at=quote.captured_at,
                )
            )
        created[event.external_id] = record

    db_session.commit()
    return created


@pytest.fixture()
def utc_now() -> datetime:
    return datetime.now(timezone.utc)
