"""agrega opportunities.probability_estimate_id

Revision ID: 0002_opp_probability_fk
Revises: 0001_initial
Create Date: 2026-09-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_opp_probability_fk"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "opportunities",
        sa.Column("probability_estimate_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_opportunities_probability_estimate_id",
        "opportunities",
        "probability_estimates",
        ["probability_estimate_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_opportunities_probability_estimate_id", "opportunities", type_="foreignkey"
    )
    op.drop_column("opportunities", "probability_estimate_id")
