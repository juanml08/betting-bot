"""esquema inicial

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(100), nullable=False, unique=True),
        sa.Column("sport", sa.String(50), nullable=False),
        sa.Column("league", sa.String(150), nullable=False),
        sa.Column("competitor_home", sa.String(150), nullable=False),
        sa.Column("competitor_away", sa.String(150), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("result", sa.String(20), nullable=True),
    )
    op.create_index("ix_events_external_id", "events", ["external_id"])

    op.create_table(
        "market_odds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("market_type", sa.String(50), nullable=False),
        sa.Column("selection", sa.String(50), nullable=False),
        sa.Column("bookmaker", sa.String(100), nullable=False),
        sa.Column("odds_value", sa.Numeric(6, 2), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_market_odds_event_id", "market_odds", ["event_id"])

    op.create_table(
        "probability_estimates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("market_type", sa.String(50), nullable=False),
        sa.Column("selection", sa.String(50), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(30), nullable=False),
        sa.Column("probability", sa.Numeric(6, 5), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_probability_estimates_event_id", "probability_estimates", ["event_id"])

    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("market_type", sa.String(50), nullable=False),
        sa.Column("selection", sa.String(50), nullable=False),
        sa.Column("bookmaker", sa.String(100), nullable=False),
        sa.Column("odds_value", sa.Numeric(6, 2), nullable=False),
        sa.Column("estimated_probability", sa.Numeric(6, 5), nullable=False),
        sa.Column("implied_probability", sa.Numeric(6, 5), nullable=False),
        sa.Column("edge", sa.Numeric(6, 5), nullable=False),
        sa.Column("expected_value", sa.Numeric(8, 5), nullable=False),
        sa.Column("kelly_fraction_suggested", sa.Numeric(6, 5), nullable=False),
        sa.Column("suggested_stake", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="candidate"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_opportunities_event_id", "opportunities", ["event_id"])

    op.create_table(
        "bets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id"), nullable=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("market_type", sa.String(50), nullable=False),
        sa.Column("selection", sa.String(50), nullable=False),
        sa.Column("odds_taken", sa.Numeric(6, 2), nullable=False),
        sa.Column("stake", sa.Numeric(10, 2), nullable=False),
        sa.Column("bankroll_at_time", sa.Numeric(12, 2), nullable=False),
        sa.Column("placed_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_bets_event_id", "bets", ["event_id"])

    op.create_table(
        "bankroll_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.String(50), nullable=False),
        sa.Column("balance_after", sa.Numeric(12, 2), nullable=False),
        sa.Column("related_bet_id", sa.Integer(), sa.ForeignKey("bets.id"), nullable=True),
    )

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_name", sa.String(100), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("num_bets", sa.Integer(), nullable=False),
        sa.Column("roi", sa.Numeric(8, 5), nullable=False),
        sa.Column("win_rate", sa.Numeric(6, 5), nullable=False),
        sa.Column("brier_score", sa.Numeric(6, 5), nullable=False),
        sa.Column("max_drawdown", sa.Numeric(8, 5), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("backtest_runs")
    op.drop_table("bankroll_transactions")
    op.drop_index("ix_bets_event_id", table_name="bets")
    op.drop_table("bets")
    op.drop_index("ix_opportunities_event_id", table_name="opportunities")
    op.drop_table("opportunities")
    op.drop_index("ix_probability_estimates_event_id", table_name="probability_estimates")
    op.drop_table("probability_estimates")
    op.drop_index("ix_market_odds_event_id", table_name="market_odds")
    op.drop_table("market_odds")
    op.drop_index("ix_events_external_id", table_name="events")
    op.drop_table("events")
