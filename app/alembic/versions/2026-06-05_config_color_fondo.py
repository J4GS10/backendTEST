"""config_color_fondo

Agrega a SYS_CONFIGURACION el color de fondo de la aplicación
(SYS_Color_Fondo), independiente del color primario (que solo tiñe el brillo
del gradiente). Permite personalizar el fondo sin tocar código.

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-06-05 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "SYS_CONFIGURACION",
        sa.Column("SYS_Color_Fondo", sa.String(length=10), nullable=True),
    )
    # Valor por defecto para la fila singleton existente: el mismo slate oscuro
    # que tenía fijo el tema (no negro puro).
    op.execute(
        "UPDATE \"SYS_CONFIGURACION\" SET \"SYS_Color_Fondo\"='#0f172a' "
        "WHERE \"SYS_Configuracion\"=1"
    )


def downgrade() -> None:
    op.drop_column("SYS_CONFIGURACION", "SYS_Color_Fondo")
