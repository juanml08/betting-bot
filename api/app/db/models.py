"""Modelos ORM (SQLAlchemy) para persistir el resultado de cada etapa del
pipeline. Son la representacion en base de datos; los objetos de dominio en
app.domain.models son los que fluyen dentro del pipeline en memoria.
"""

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    sport: Mapped[str] = mapped_column(String(50))
    league: Mapped[str] = mapped_column(String(150))
    competitor_home: Mapped[str] = mapped_column(String(150))
    competitor_away: Mapped[str] = mapped_column(String(150))
    start_time: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(100))
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)

    odds_quotes: Mapped[list["MarketOdds"]] = relationship(back_populates="event")
    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="event")


class MarketOdds(Base):
    __tablename__ = "market_odds"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    market_type: Mapped[str] = mapped_column(String(50))
    selection: Mapped[str] = mapped_column(String(50))
    bookmaker: Mapped[str] = mapped_column(String(100))
    odds_value: Mapped[float] = mapped_column(Numeric(6, 2))
    captured_at: Mapped[datetime] = mapped_column(DateTime)

    event: Mapped["Event"] = relationship(back_populates="odds_quotes")


class ProbabilityEstimateRecord(Base):
    __tablename__ = "probability_estimates"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    market_type: Mapped[str] = mapped_column(String(50))
    selection: Mapped[str] = mapped_column(String(50))
    model_name: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str] = mapped_column(String(30))
    probability: Mapped[float] = mapped_column(Numeric(6, 5))
    computed_at: Mapped[datetime] = mapped_column(DateTime)


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    market_type: Mapped[str] = mapped_column(String(50))
    selection: Mapped[str] = mapped_column(String(50))
    bookmaker: Mapped[str] = mapped_column(String(100))
    odds_value: Mapped[float] = mapped_column(Numeric(6, 2))
    estimated_probability: Mapped[float] = mapped_column(Numeric(6, 5))
    implied_probability: Mapped[float] = mapped_column(Numeric(6, 5))
    edge: Mapped[float] = mapped_column(Numeric(6, 5))
    expected_value: Mapped[float] = mapped_column(Numeric(8, 5))
    kelly_fraction_suggested: Mapped[float] = mapped_column(Numeric(6, 5))
    suggested_stake: Mapped[float] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    created_at: Mapped[datetime] = mapped_column(DateTime)

    event: Mapped["Event"] = relationship(back_populates="opportunities")
    bets: Mapped[list["Bet"]] = relationship(back_populates="opportunity")


class Bet(Base):
    """Registro MANUAL de una apuesta ya realizada por el usuario fuera del sistema.

    El sistema nunca crea filas aqui automaticamente: siempre se registran a
    traves del endpoint de bets tras la decision humana.
    """

    __tablename__ = "bets"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"), nullable=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    market_type: Mapped[str] = mapped_column(String(50))
    selection: Mapped[str] = mapped_column(String(50))
    odds_taken: Mapped[float] = mapped_column(Numeric(6, 2))
    stake: Mapped[float] = mapped_column(Numeric(10, 2))
    bankroll_at_time: Mapped[float] = mapped_column(Numeric(12, 2))
    placed_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    opportunity: Mapped["Opportunity | None"] = relationship(back_populates="bets")


class BankrollTransaction(Base):
    __tablename__ = "bankroll_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    reason: Mapped[str] = mapped_column(String(50))
    balance_after: Mapped[float] = mapped_column(Numeric(12, 2))
    related_bet_id: Mapped[int | None] = mapped_column(ForeignKey("bets.id"), nullable=True)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String(100))
    params: Mapped[dict] = mapped_column(JSON)
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    num_bets: Mapped[int] = mapped_column()
    roi: Mapped[float] = mapped_column(Numeric(8, 5))
    win_rate: Mapped[float] = mapped_column(Numeric(6, 5))
    brier_score: Mapped[float] = mapped_column(Numeric(6, 5))
    max_drawdown: Mapped[float] = mapped_column(Numeric(8, 5))
    created_at: Mapped[datetime] = mapped_column(DateTime)
