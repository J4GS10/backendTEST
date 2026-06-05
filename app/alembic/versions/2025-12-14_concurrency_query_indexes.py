"""concurrency_query_indexes

Mejoras de concurrencia y rendimiento de consultas:

1. uq_mantenimiento_activo_abierto — índice ÚNICO PARCIAL que garantiza, a
   nivel de base de datos, que un activo no pueda tener más de UN mantenimiento
   abierto a la vez (antes solo lo validaba un SELECT en el servicio, sujeto a
   race condition TOCTOU bajo concurrencia). Espejo del que ya protege a
   INV_MOVIMIENTO.

2. Índices para consultas calientes que hacían seq-scan:
   - ix_movimiento_activo / ix_mantenimiento_activo: historial por activo.
   - ix_movimiento_persona / ix_movimiento_area: declarados en el modelo pero
     ausentes en la BD (drift modelo↔migración); se sincronizan aquí.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2025-12-14 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    where_open = sa.text('"MAN_Fecha_Cierre" IS NULL')
    if bind.dialect.name == "postgresql":
        op.create_index(
            "uq_mantenimiento_activo_abierto", "INV_MANTENIMIENTO", ["ACT_Activo"],
            unique=True, postgresql_where=where_open,
        )
    else:
        op.create_index(
            "uq_mantenimiento_activo_abierto", "INV_MANTENIMIENTO", ["ACT_Activo"],
            unique=True, sqlite_where=where_open,
        )
    op.create_index("ix_mantenimiento_activo", "INV_MANTENIMIENTO", ["ACT_Activo"])
    op.create_index("ix_movimiento_activo", "INV_MOVIMIENTO", ["ACT_Activo"])
    op.create_index("ix_movimiento_persona", "INV_MOVIMIENTO", ["PER_Persona"])
    op.create_index("ix_movimiento_area", "INV_MOVIMIENTO", ["ARE_Area"])


def downgrade() -> None:
    op.drop_index("ix_movimiento_area", table_name="INV_MOVIMIENTO")
    op.drop_index("ix_movimiento_persona", table_name="INV_MOVIMIENTO")
    op.drop_index("ix_movimiento_activo", table_name="INV_MOVIMIENTO")
    op.drop_index("ix_mantenimiento_activo", table_name="INV_MANTENIMIENTO")
    op.drop_index("uq_mantenimiento_activo_abierto", table_name="INV_MANTENIMIENTO")
