from fastapi import APIRouter

from app.api.v1.endpoints import backtest, bankroll, bets, events, opportunities

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(events.router)
api_router.include_router(opportunities.router)
api_router.include_router(bets.router)
api_router.include_router(bankroll.router)
api_router.include_router(backtest.router)
