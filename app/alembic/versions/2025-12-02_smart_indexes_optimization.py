"""smart_indexes_optimization

Revision ID: e6094e1f8aee
Revises: e92cb9051d12
Create Date: 2025-12-02 19:15:26.370171+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6094e1f8aee'
down_revision: Union[str, Sequence[str], None] = 'e92cb9051d12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================
    # 1. ÍNDICES DE BÚSQUEDA
    # =========================================================
    op.create_index('ix_inv_activo_serie', 'INV_ACTIVO', ['ACT_Serie_Fabricante'])
    op.create_index('ix_inv_activo_hostname', 'INV_ACTIVO', ['ACT_Hostname'])
    
    # Usamos índice compuesto para nombres
    op.create_index('ix_inv_persona_nombres', 'INV_PERSONA', ['PER_Primer_Nombre', 'PER_Primer_Apellido'])

    # =========================================================
    # 2. ÍNDICES DE CRONOLOGÍA
    # =========================================================
    op.create_index('ix_movimiento_fecha', 'INV_MOVIMIENTO', ['MOV_Fecha_Asignacion'])
    op.create_index('ix_mantenimiento_fecha', 'INV_MANTENIMIENTO', ['MAN_Fecha_Ingreso'])

    # =========================================================
    # 3. ÍNDICES PARCIALES (Optimización Avanzada)
    # =========================================================
    # Solo indexa los activos asignados actualmente (donde fecha fin es NULL)
    op.create_index(
        'ix_movimiento_activo_vigente', 
        'INV_MOVIMIENTO', 
        ['ACT_Activo'], 
        postgresql_where=sa.text('"MOV_Fecha_Devolucion" IS NULL')
    )

    # Solo indexa licencias instaladas (estado TRUE)
    op.create_index(
        'ix_instalacion_activa',
        'INV_INSTALACION',
        ['LIC_Licencia'],
        postgresql_where=sa.text('"INS_Estado" = true')
    )


def downgrade() -> None:
    op.drop_index('ix_inv_activo_serie', table_name='INV_ACTIVO')
    op.drop_index('ix_inv_activo_hostname', table_name='INV_ACTIVO')
    op.drop_index('ix_inv_persona_nombres', table_name='INV_PERSONA')
    op.drop_index('ix_movimiento_fecha', table_name='INV_MOVIMIENTO')
    op.drop_index('ix_mantenimiento_fecha', table_name='INV_MANTENIMIENTO')
    op.drop_index('ix_movimiento_activo_vigente', table_name='INV_MOVIMIENTO')
    op.drop_index('ix_instalacion_activa', table_name='INV_INSTALACION')