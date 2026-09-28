"""Paleta por defecto unificada ("Neutro Cálido").

La BD traía por defecto una paleta oscura heredada (#0f172a / #1e293b /
#3b82f6) que el frontend nunca mostraba tal cual (mezclaba el fondo hacia
crema). Ahora el tema respeta el color configurado, así que las instalaciones
que conservan EXACTAMENTE la paleta heredada pasan a la paleta por defecto,
que es lo que ya veían. Paletas personalizadas no se tocan.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-24
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE "SYS_CONFIGURACION"
           SET "SYS_Color_Fondo" = '#f5f3ef',
               "SYS_Color_Primario" = '#4a7c9e',
               "SYS_Color_Secundario" = '#5a8e7a'
         WHERE lower("SYS_Color_Fondo") = '#0f172a'
           AND lower("SYS_Color_Primario") = '#1e293b'
           AND lower("SYS_Color_Secundario") = '#3b82f6'
        """
    )


def downgrade() -> None:
    pass  # cambio de datos cosmético; no se revierte
