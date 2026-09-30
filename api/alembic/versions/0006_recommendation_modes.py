"""agrega mode y decision_metadata a recommendations

Revision ID: 0006_recommendation_modes
Revises: 0005_bet_leg_event_uq
Create Date: 2026-09-29

- mode ('real' | 'trial'): obligatorio. Se verifico antes de escribir esta
  migracion que `recommendations` estaba vacia (SELECT COUNT(*) = 0), por lo
  que se agrega directamente NOT NULL y sin server_default: toda
  Recommendation nueva debe declarar su modo explicitamente. Si en otro
  entorno hubiera filas, el ALTER fallaria en vez de asignar en silencio un
  modo que no fue decidido.
- decision_metadata: JSON nullable (snapshot opcional de la decision).
- bet_type ya es VARCHAR(20) sin CHECK constraint, por lo que aceptar
  'no_bet' es solo validacion de aplicacion (RecommendationService); no
  requiere cambio de esquema.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_recommendation_modes"
down_revision: Union[str, None] = "0005_bet_leg_event_uq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recommendations", sa.Column("mode", sa.String(20), nullable=False))
    op.add_column("recommendations", sa.Column("decision_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("recommendations", "decision_metadata")
    op.drop_column("recommendations", "mode")
