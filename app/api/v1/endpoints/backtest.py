from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_opportunity_filter, get_risk_manager
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.db.models import BacktestRun
from app.ingestion.providers.sample_data_provider import SampleDataProvider
from app.models.generic_rating_model import GenericRatingModel
from app.odds.providers.sample_odds_provider import SampleOddsProvider
from app.schemas.backtest import BacktestRequest, BacktestResult
from backtesting.engine import BacktestEngine
from backtesting.metrics import compute_metrics

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.post("/run", response_model=BacktestResult)
def run_backtest(
    payload: BacktestRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BacktestResult:
    """Ejecuta un backtest sobre los proveedores de datos configurados y
    persiste el resultado para poder comparar estrategias en el tiempo."""
    model = GenericRatingModel()
    engine = BacktestEngine(
        data_provider=SampleDataProvider(),
        odds_provider=SampleOddsProvider(),
        probability_model=model,
        opportunity_filter=get_opportunity_filter(settings),
        risk_manager=get_risk_manager(settings),
    )

    report = engine.run(
        initial_bankroll=settings.initial_bankroll,
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
    metrics = compute_metrics(report)

    run = BacktestRun(
        strategy_name=model.name,
        params={
            "kelly_fraction": settings.kelly_fraction,
            "min_edge": settings.min_edge,
            "min_expected_value": settings.min_expected_value,
        },
        date_from=payload.date_from,
        date_to=payload.date_to,
        num_bets=metrics.num_bets,
        roi=metrics.roi,
        win_rate=metrics.win_rate,
        brier_score=metrics.brier_score,
        max_drawdown=metrics.max_drawdown,
        created_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    return BacktestResult(
        strategy_name=run.strategy_name,
        date_from=run.date_from,
        date_to=run.date_to,
        num_bets=run.num_bets,
        roi=float(run.roi),
        win_rate=float(run.win_rate),
        brier_score=float(run.brier_score),
        max_drawdown=float(run.max_drawdown),
        created_at=run.created_at,
    )
