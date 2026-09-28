"""Performance: partial index on open movements for active-assignment checks.

Adds a partial index on INV_MOVIMIENTO(ACT_Activo) filtered to rows where
MOV_Fecha_Devolucion IS NULL. This is the predicate used in delete_activo
and any query that checks whether an asset has an active open movement.

Revision ID: b9c8d7e6f5a4
Revises: a1b2c3d4e5f6
Create Date: 2026-09-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9c8d7e6f5a4"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Partial index: only rows with no return date (active movements).
    # Converts the O(n) scan in active-assignment checks to O(log n).
    # PostgreSQL-only predicate; SQLite and Oracle silently ignore it
    # (op.create_index falls back to a full index on those dialects).
    op.create_index(
        "ix_movimiento_activo_abierto",
        "INV_MOVIMIENTO",
        ["ACT_Activo"],
        postgresql_where=sa.text('"MOV_Fecha_Devolucion" IS NULL'),
    )


def downgrade() -> None:
    op.drop_index("ix_movimiento_activo_abierto", table_name="INV_MOVIMIENTO")
