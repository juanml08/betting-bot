"""crea recommendations y recommendation_opportunities

Revision ID: 0003_recommendations
Revises: 0002_opp_probability_fk
Create Date: 2026-09-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_recommendations"
down_revision: Union[str, None] = "0002_opp_probability_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_name", sa.String(100), nullable=False),
        sa.Column("strategy_params", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("bet_type", sa.String(20), nullable=False),
        sa.Column("bankroll_at_recommendation", sa.Numeric(12, 2), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "recommendation_opportunities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recommendation_id", sa.Integer(), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("leg_order", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_recommendation_opportunities_recommendation_id",
        "recommendation_opportunities",
        ["recommendation_id"],
    )
    op.create_index(
        "ix_recommendation_opportunities_opportunity_id",
        "recommendation_opportunities",
        ["opportunity_id"],
    )
    op.create_foreign_key(
        "fk_recommendation_opportunities_recommendation_id",
        "recommendation_opportunities",
        "recommendations",
        ["recommendation_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_recommendation_opportunities_opportunity_id",
        "recommendation_opportunities",
        "opportunities",
        ["opportunity_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_recommendation_opportunities_leg_order",
        "recommendation_opportunities",
        ["recommendation_id", "leg_order"],
    )
    op.create_unique_constraint(
        "uq_recommendation_opportunities_opportunity",
        "recommendation_opportunities",
        ["recommendation_id", "opportunity_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_recommendation_opportunities_opportunity",
        "recommendation_opportunities",
        type_="unique",
    )
    op.drop_constraint(
        "uq_recommendation_opportunities_leg_order",
        "recommendation_opportunities",
        type_="unique",
    )
    op.drop_constraint(
        "fk_recommendation_opportunities_opportunity_id",
        "recommendation_opportunities",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_recommendation_opportunities_recommendation_id",
        "recommendation_opportunities",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_recommendation_opportunities_opportunity_id",
        table_name="recommendation_opportunities",
    )
    op.drop_index(
        "ix_recommendation_opportunities_recommendation_id",
        table_name="recommendation_opportunities",
    )
    op.drop_table("recommendation_opportunities")
    op.drop_table("recommendations")
