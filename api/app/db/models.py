"""Modelos ORM (SQLAlchemy) para persistir el resultado de cada etapa del
pipeline. Son la representacion en base de datos; los objetos de dominio en
app.domain.models son los que fluyen dentro del pipeline en memoria.
"""

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy import inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

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
    """Version de un slot (event_id, market_type, selection, bookmaker).

    Ciclo de vida (ver OpportunityLifecycleService): una fila es un snapshot
    inmutable de la decision (cuota + probabilidad). Si cambia cualquiera de
    las dos se crea una version nueva y la anterior queda 'superseded'; si
    deja de ser valida sin reemplazo queda 'expired'. Solo la ultima version
    de un slot puede ser 'candidate'.

    Solo son mutables por el lifecycle: status, superseded_at,
    superseded_by_id y last_observed_at (ultima observacion valida del slot
    por el proveedor, no el momento de persistencia: ese es created_at).
    """

    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "market_type",
            "selection",
            "bookmaker",
            "version",
            name="uq_opportunities_slot_version",
        ),
        Index("ix_opportunities_status_last_observed_at", "status", "last_observed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    probability_estimate_id: Mapped[int | None] = mapped_column(
        ForeignKey("probability_estimates.id"), nullable=True
    )
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
    version: Mapped[int] = mapped_column(default=1)
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda ctx: ctx.get_current_parameters()["created_at"]
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunities.id"), nullable=True
    )

    event: Mapped["Event"] = relationship(back_populates="opportunities")

    @validates(
        "event_id",
        "market_type",
        "selection",
        "bookmaker",
        "odds_value",
        "estimated_probability",
        "implied_probability",
        "edge",
        "expected_value",
        "kelly_fraction_suggested",
        "suggested_stake",
        "created_at",
    )
    def _decision_fields_are_immutable(self, key, value):
        """Los campos de decision son un snapshot historico: se fijan al crear
        la Opportunity y no pueden reasignarse una vez persistida. Protege la
        ruta ORM; un UPDATE directo por SQL/bulk update no pasa por aqui."""
        if inspect(self).has_identity:
            raise ValueError(f"Opportunity.{key} es inmutable una vez creada la Opportunity")
        return value


class Recommendation(Base):
    """Snapshot inmutable de una decision del bot: que Opportunity(ies)
    recomienda, con que estrategia y contra que banca, en un momento dado.

    No se actualiza tras crearse: cambios posteriores en las Opportunities
    referenciadas (via RecommendationOpportunity) no alteran este registro.

    mode ('real' | 'trial') indica si la decision es para dinero real o para
    TRIAL (dinero ficticio). bet_type puede ser 'simple', 'compound' o
    'no_bet' (decision de no apostar: 0 RecommendationOpportunity); 'no_bet'
    pertenece solo a Recommendation, nunca a Bet. decision_metadata es un
    snapshot JSON opcional del razonamiento de la decision, sin estructura
    fija todavia.
    """

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(20))
    strategy_name: Mapped[str] = mapped_column(String(100))
    strategy_params: Mapped[dict] = mapped_column(JSON)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    bet_type: Mapped[str] = mapped_column(String(20))
    decision_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    bankroll_at_recommendation: Mapped[float] = mapped_column(Numeric(12, 2))
    generated_at: Mapped[datetime] = mapped_column(DateTime)

    legs: Mapped[list["RecommendationOpportunity"]] = relationship(
        back_populates="recommendation",
        order_by="RecommendationOpportunity.leg_order",
    )


class RecommendationOpportunity(Base):
    """Vincula una Recommendation con una o mas Opportunity, preservando el
    orden (leg_order) con el que se armo la seleccion/combinada."""

    __tablename__ = "recommendation_opportunities"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_id", "leg_order", name="uq_recommendation_opportunities_leg_order"
        ),
        UniqueConstraint(
            "recommendation_id", "opportunity_id", name="uq_recommendation_opportunities_opportunity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), index=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    leg_order: Mapped[int] = mapped_column()

    recommendation: Mapped["Recommendation"] = relationship(back_populates="legs")
    opportunity: Mapped["Opportunity"] = relationship()


class Bet(Base):
    """Apuesta ya colocada: manual (por un humano, mode='real') o, mas
    adelante, generada automaticamente por TRIAL (mode='trial') con dinero
    ficticio. Es un contenedor de 1 a 3 BetLeg (1 para 'simple', 2-3 para
    'compound').

    No incluye el resultado economico: eso es responsabilidad de Settlement,
    para mantener separado el estado operativo (pending/settled) del
    resultado final (won/lost/void/manual_review).

    Cuando se origina desde una Recommendation ya decidida, recommendation_id
    la referencia (UNIQUE: una Recommendation origina como maximo un Bet).
    Un Bet manual, registrado sin pasar por una Recommendation, la deja NULL.
    """

    __tablename__ = "bets"

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int | None] = mapped_column(
        ForeignKey("recommendations.id"), unique=True, nullable=True
    )
    bet_type: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(20), default="real")
    stake: Mapped[float] = mapped_column(Numeric(10, 2))
    bankroll_at_time: Mapped[float] = mapped_column(Numeric(12, 2))
    placed_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    legs: Mapped[list["BetLeg"]] = relationship(
        back_populates="bet", order_by="BetLeg.leg_order"
    )
    settlement: Mapped["Settlement | None"] = relationship(back_populates="bet")


class BetLeg(Base):
    """Una seleccion individual dentro de un Bet. 'simple' tiene exactamente
    una; 'compound' entre 2 y 3, cada una de un event_id distinto.

    No referencia a Opportunity directamente (evita una relacion redundante):
    cuando el Bet viene de una Recommendation, que Opportunity origino cada
    leg se reconstruye cruzando Bet.recommendation_id ->
    RecommendationOpportunity.leg_order == BetLeg.leg_order.
    """

    __tablename__ = "bet_legs"
    __table_args__ = (
        UniqueConstraint("bet_id", "leg_order", name="uq_bet_legs_leg_order"),
        UniqueConstraint("bet_id", "event_id", name="uq_bet_legs_bet_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bet_id: Mapped[int] = mapped_column(ForeignKey("bets.id"), index=True)
    leg_order: Mapped[int] = mapped_column()
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    market_type: Mapped[str] = mapped_column(String(50))
    selection: Mapped[str] = mapped_column(String(50))
    bookmaker: Mapped[str] = mapped_column(String(100))
    odds_taken: Mapped[float] = mapped_column(Numeric(6, 2))
    result: Mapped[str] = mapped_column(String(20), default="pending")

    bet: Mapped["Bet"] = relationship(back_populates="legs")
    event: Mapped["Event"] = relationship()

    @validates("odds_taken")
    def _odds_taken_is_immutable(self, key, value):
        """odds_taken es un snapshot historico: se fija al crear el BetLeg y
        no puede reasignarse una vez persistido. Protege la ruta ORM; un
        UPDATE directo por SQL/bulk update no pasa por aqui."""
        if inspect(self).has_identity:
            raise ValueError("BetLeg.odds_taken es inmutable una vez creado el BetLeg")
        return value


class Settlement(Base):
    """Resultado economico final de un Bet (entidad separada del Bet en si,
    para no mezclar estado operativo con resultado). A lo sumo un Settlement
    por Bet (bet_id UNIQUE): una vez creado, no se recalcula ni se reemplaza,
    incluso si su status es 'manual_review' (ver SettlementService para las
    reglas de agregacion de resultados de legs y de idempotencia)."""

    __tablename__ = "settlements"

    id: Mapped[int] = mapped_column(primary_key=True)
    bet_id: Mapped[int] = mapped_column(ForeignKey("bets.id"), unique=True)
    settled_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20))
    payout: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    profit_loss: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    bet: Mapped["Bet"] = relationship(back_populates="settlement")


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
