"""ciclo de vida de opportunities: version, last_observed_at, supersession

Revision ID: 0007_opportunity_lifecycle
Revises: 0006_recommendation_modes
Create Date: 2026-09-29

Agrega version / last_observed_at / superseded_at / superseded_by_id y el
UNIQUE (event_id, market_type, selection, bookmaker, version).

Backfill (antes de crear el UNIQUE), por slot:
- Se normaliza market_type/selection/bookmaker con strip().lower() (misma
  identidad que usa OpportunityLifecycleService). Es el unico cambio sobre
  columnas de decision historicas y es solo de casing/espacios; el downgrade
  no puede restaurar el casing original.
- Las filas del slot se ordenan por (created_at, id) y reciben version 1..N.
- Las versiones anteriores a la ultima quedan 'superseded', con
  superseded_at = created_at del sucesor y superseded_by_id = id del sucesor.
- La ultima version conserva su status (en datos historicos siempre es
  'candidate'); no se le impone 'candidate' si ya era otro estado.
- last_observed_at = created_at. Nunca se borra ninguna fila (pueden estar
  referenciadas por recommendation_opportunities).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_opportunity_lifecycle"
down_revision: Union[str, None] = "0006_recommendation_modes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UQ = "uq_opportunities_slot_version"
_FK = "fk_opportunities_superseded_by_id"
_IX = "ix_opportunities_status_last_observed_at"


def _norm(value: str) -> str:
    return value.strip().lower()


def upgrade() -> None:
    op.add_column(
        "opportunities",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("opportunities", sa.Column("last_observed_at", sa.DateTime(), nullable=True))
    op.add_column("opportunities", sa.Column("superseded_at", sa.DateTime(), nullable=True))
    op.add_column("opportunities", sa.Column("superseded_by_id", sa.Integer(), nullable=True))

    _backfill()

    op.alter_column("opportunities", "last_observed_at", existing_type=sa.DateTime(), nullable=False)
    op.alter_column(
        "opportunities", "version", existing_type=sa.Integer(), nullable=False, server_default=None
    )
    op.create_foreign_key(_FK, "opportunities", "opportunities", ["superseded_by_id"], ["id"])
    op.create_unique_constraint(
        _UQ, "opportunities", ["event_id", "market_type", "selection", "bookmaker", "version"]
    )
    op.create_index(_IX, "opportunities", ["status", "last_observed_at"])


def _backfill() -> None:
    bind = op.get_bind()
    opps = sa.table(
        "opportunities",
        sa.column("id", sa.Integer),
        sa.column("event_id", sa.Integer),
        sa.column("market_type", sa.String),
        sa.column("selection", sa.String),
        sa.column("bookmaker", sa.String),
        sa.column("status", sa.String),
        sa.column("created_at", sa.DateTime),
        sa.column("version", sa.Integer),
        sa.column("last_observed_at", sa.DateTime),
        sa.column("superseded_at", sa.DateTime),
        sa.column("superseded_by_id", sa.Integer),
    )
    rows = bind.execute(
        sa.select(
            opps.c.id,
            opps.c.event_id,
            opps.c.market_type,
            opps.c.selection,
            opps.c.bookmaker,
            opps.c.created_at,
        ).order_by(opps.c.created_at, opps.c.id)
    ).all()

    slots: dict[tuple, list] = {}
    for row in rows:
        key = (row.event_id, _norm(row.market_type), _norm(row.selection), _norm(row.bookmaker))
        slots.setdefault(key, []).append(row)

    for (_, market_type, selection, bookmaker), versions in slots.items():
        for index, row in enumerate(versions):
            values = {
                "market_type": market_type,
                "selection": selection,
                "bookmaker": bookmaker,
                "version": index + 1,
                "last_observed_at": row.created_at,
            }
            if index + 1 < len(versions):
                successor = versions[index + 1]
                values.update(
                    status="superseded",
                    superseded_at=successor.created_at,
                    superseded_by_id=successor.id,
                )
            bind.execute(sa.update(opps).where(opps.c.id == row.id).values(**values))


def downgrade() -> None:
    op.drop_index(_IX, table_name="opportunities")
    op.drop_constraint(_UQ, "opportunities", type_="unique")
    op.drop_constraint(_FK, "opportunities", type_="foreignkey")
    op.drop_column("opportunities", "superseded_by_id")
    op.drop_column("opportunities", "superseded_at")
    op.drop_column("opportunities", "last_observed_at")
    op.drop_column("opportunities", "version")
