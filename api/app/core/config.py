from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "mysql+pymysql://betting_user:betting_password@localhost:3306/betting_bot"

    # Gestion de riesgo / banca. Estos son valores por defecto: no son garantia de
    # rentabilidad, son limites de exposicion que el usuario debe calibrar.
    initial_bankroll: float = 1000.0
    kelly_fraction: float = 0.25
    max_stake_pct_per_bet: float = 0.05
    max_daily_exposure_pct: float = 0.20

    # Filtros minimos para que una oportunidad se considere candidata.
    min_edge: float = 0.03
    min_expected_value: float = 0.0
    min_odds: float = 1.3
    max_odds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
