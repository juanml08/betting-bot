"""Corre un backtest sobre los datos de muestra y muestra las metricas por consola.

Uso: poetry run python scripts/run_backtest.py
"""

from datetime import date

from app.api.deps import get_opportunity_filter, get_risk_manager
from app.core.config import get_settings
from app.ingestion.providers.sample_data_provider import SampleDataProvider
from app.models.generic_rating_model import GenericRatingModel
from app.odds.providers.sample_odds_provider import SampleOddsProvider
from backtesting.engine import BacktestEngine
from backtesting.metrics import compute_metrics


def main() -> None:
    settings = get_settings()

    engine = BacktestEngine(
        data_provider=SampleDataProvider(),
        odds_provider=SampleOddsProvider(),
        probability_model=GenericRatingModel(),
        opportunity_filter=get_opportunity_filter(settings),
        risk_manager=get_risk_manager(settings),
    )

    report = engine.run(
        initial_bankroll=settings.initial_bankroll,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 31),
    )
    metrics = compute_metrics(report)

    print("--- Resultado del backtest (datos de muestra, NO es una garantia de rentabilidad) ---")
    print(f"Apuestas simuladas: {metrics.num_bets}")
    print(f"Total apostado:     {metrics.total_staked:.2f}")
    print(f"Beneficio total:    {metrics.total_profit:.2f}")
    print(f"ROI:                {metrics.roi:.2%}")
    print(f"Win rate:           {metrics.win_rate:.2%}")
    print(f"Brier score:        {metrics.brier_score:.4f} (mas bajo = mejor calibracion)")
    print(f"Max drawdown:       {metrics.max_drawdown:.2%}")
    print(f"Banca inicial:      {report.initial_bankroll:.2f}")
    print(f"Banca final:        {report.final_bankroll:.2f}")


if __name__ == "__main__":
    main()
