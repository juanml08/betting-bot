"""agrega UNIQUE (bet_id, event_id) a bet_legs

Revision ID: 0005_bet_leg_event_uq
Revises: 0004_bet_settlement
Create Date: 2026-09-29

Segunda linea de defensa de la regla "un Bet no puede tener dos BetLeg del
mismo event_id" (la primera es BetService). No toca la migracion 0004.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005_bet_leg_event_uq"
down_revision: Union[str, None] = "0004_bet_settlement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_bet_legs_bet_event", "bet_legs", ["bet_id", "event_id"])


def downgrade() -> None:
    # En MySQL, ix_bet_legs_bet_id / fk_bet_legs_bet_id pueden apoyarse en el
    # indice del UNIQUE (bet_id, ...); uq_bet_legs_leg_order y ix_bet_legs_bet_id
    # cubren bet_id, asi que soltar este unique es seguro.
    op.drop_constraint("uq_bet_legs_bet_event", "bet_legs", type_="unique")
