"""reestructura bets en Bet + BetLeg, agrega settlements

Revision ID: 0004_bet_settlement
Revises: 0003_recommendations
Create Date: 2026-09-21

La tabla `bets` original (una sola seleccion por fila: event_id, market_type,
selection, odds_taken, settled_at) se reemplaza por Bet (contenedor,
1 a 3 legs) + BetLeg (una fila por seleccion) + Settlement (resultado
economico final, entidad separada del estado operativo de Bet).

Se verifico antes de escribir esta migracion que `bets` no tenia filas en
ningun entorno (SELECT COUNT(*) FROM bets = 0), por lo que se reemplaza la
tabla directamente en vez de migrar datos existentes.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_bet_settlement"
down_revision: Union[str, None] = "0003_recommendations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # bankroll_transactions.related_bet_id apunta a bets.id: hay que soltar
    # esa FK antes de poder tirar la tabla bets vieja.
    op.drop_constraint(
        "bankroll_transactions_ibfk_1", "bankroll_transactions", type_="foreignkey"
    )
    op.drop_constraint("bets_ibfk_1", "bets", type_="foreignkey")
    op.drop_constraint("bets_ibfk_2", "bets", type_="foreignkey")

    op.drop_index("ix_bets_event_id", table_name="bets")
    op.drop_table("bets")

    op.create_table(
        "bets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recommendation_id", sa.Integer(), nullable=True),
        sa.Column("bet_type", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False, server_default="real"),
        sa.Column("stake", sa.Numeric(10, 2), nullable=False),
        sa.Column("bankroll_at_time", sa.Numeric(12, 2), nullable=False),
        sa.Column("placed_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_bets_recommendation_id",
        "bets",
        "recommendations",
        ["recommendation_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_bets_recommendation_id", "bets", ["recommendation_id"]
    )

    op.create_foreign_key(
        "fk_bankroll_transactions_related_bet_id",
        "bankroll_transactions",
        "bets",
        ["related_bet_id"],
        ["id"],
    )

    op.create_table(
        "bet_legs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bet_id", sa.Integer(), nullable=False),
        sa.Column("leg_order", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("market_type", sa.String(50), nullable=False),
        sa.Column("selection", sa.String(50), nullable=False),
        sa.Column("bookmaker", sa.String(100), nullable=False),
        sa.Column("odds_taken", sa.Numeric(6, 2), nullable=False),
        sa.Column("result", sa.String(20), nullable=False, server_default="pending"),
    )
    op.create_index("ix_bet_legs_bet_id", "bet_legs", ["bet_id"])
    op.create_index("ix_bet_legs_event_id", "bet_legs", ["event_id"])
    op.create_foreign_key(
        "fk_bet_legs_bet_id", "bet_legs", "bets", ["bet_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_bet_legs_event_id", "bet_legs", "events", ["event_id"], ["id"]
    )
    op.create_unique_constraint(
        "uq_bet_legs_leg_order", "bet_legs", ["bet_id", "leg_order"]
    )

    op.create_table(
        "settlements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bet_id", sa.Integer(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payout", sa.Numeric(10, 2), nullable=True),
        sa.Column("profit_loss", sa.Numeric(10, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_settlements_bet_id", "settlements", "bets", ["bet_id"], ["id"]
    )
    op.create_unique_constraint("uq_settlements_bet_id", "settlements", ["bet_id"])


def downgrade() -> None:
    op.drop_constraint("fk_settlements_bet_id", "settlements", type_="foreignkey")
    op.drop_constraint("uq_settlements_bet_id", "settlements", type_="unique")
    op.drop_table("settlements")

    op.drop_constraint("uq_bet_legs_leg_order", "bet_legs", type_="unique")
    op.drop_constraint("fk_bet_legs_event_id", "bet_legs", type_="foreignkey")
    op.drop_constraint("fk_bet_legs_bet_id", "bet_legs", type_="foreignkey")
    op.drop_index("ix_bet_legs_event_id", table_name="bet_legs")
    op.drop_index("ix_bet_legs_bet_id", table_name="bet_legs")
    op.drop_table("bet_legs")

    op.drop_constraint(
        "fk_bankroll_transactions_related_bet_id", "bankroll_transactions", type_="foreignkey"
    )

    op.drop_constraint("fk_bets_recommendation_id", "bets", type_="foreignkey")
    op.drop_constraint("uq_bets_recommendation_id", "bets", type_="unique")
    op.drop_table("bets")

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

    # Se restaura con el mismo nombre auto-generado que tenia originalmente
    # (ver 0001_initial_schema), para que un upgrade posterior -- que espera
    # ese nombre exacto para poder soltarla -- funcione igual sin importar
    # si viene de un downgrade o de una base nueva.
    op.create_foreign_key(
        "bankroll_transactions_ibfk_1",
        "bankroll_transactions",
        "bets",
        ["related_bet_id"],
        ["id"],
    )
