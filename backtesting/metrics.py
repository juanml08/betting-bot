"""Etapa METRICAS / EVALUACION DE LA ESTRATEGIA.

Toma el resultado de un BacktestReport y calcula indicadores objetivos.
Ninguno de estos numeros por si solo demuestra que una estrategia es
rentable a largo plazo: hacen falta muestras suficientes y validacion fuera
de la muestra antes de confiar en una estrategia.
"""

from dataclasses import dataclass

from backtesting.engine import BacktestReport


@dataclass
class StrategyMetrics:
    num_bets: int
    total_staked: float
    total_profit: float
    roi: float
    win_rate: float
    brier_score: float
    max_drawdown: float


def compute_metrics(report: BacktestReport) -> StrategyMetrics:
    records = report.records
    num_bets = len(records)

    if num_bets == 0:
        return StrategyMetrics(
            num_bets=0,
            total_staked=0.0,
            total_profit=0.0,
            roi=0.0,
            win_rate=0.0,
            brier_score=0.0,
            max_drawdown=0.0,
        )

    total_staked = sum(r.stake for r in records)
    total_profit = sum(r.profit for r in records)
    roi = total_profit / total_staked if total_staked > 0 else 0.0
    win_rate = sum(1 for r in records if r.won) / num_bets

    brier_score = sum(
        (r.estimated_probability - (1.0 if r.won else 0.0)) ** 2 for r in records
    ) / num_bets

    max_drawdown = _max_drawdown([report.initial_bankroll] + [r.bankroll_after for r in records])

    return StrategyMetrics(
        num_bets=num_bets,
        total_staked=total_staked,
        total_profit=total_profit,
        roi=roi,
        win_rate=win_rate,
        brier_score=brier_score,
        max_drawdown=max_drawdown,
    )


def _max_drawdown(bankroll_curve: list[float]) -> float:
    peak = bankroll_curve[0]
    max_dd = 0.0
    for value in bankroll_curve:
        peak = max(peak, value)
        if peak > 0:
            drawdown = (peak - value) / peak
            max_dd = max(max_dd, drawdown)
    return max_dd
