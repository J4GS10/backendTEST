"""config_acta_fields

Agrega a SYS_CONFIGURACION los campos del encabezado de las actas:
código de formulario y ciudad (antes eran constantes en el código).

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2025-12-17 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("SYS_CONFIGURACION", sa.Column("SYS_Codigo_Formulario", sa.String(length=50), nullable=True))
    op.add_column("SYS_CONFIGURACION", sa.Column("SYS_Ciudad", sa.String(length=60), nullable=True))
    # Valores por defecto razonables para la fila singleton existente.
    op.execute(
        "UPDATE \"SYS_CONFIGURACION\" SET \"SYS_Codigo_Formulario\"='F.IT.GUA.04.01', "
        "\"SYS_Ciudad\"='Guatemala' WHERE \"SYS_Configuracion\"=1"
    )


def downgrade() -> None:
    op.drop_column("SYS_CONFIGURACION", "SYS_Ciudad")
    op.drop_column("SYS_CONFIGURACION", "SYS_Codigo_Formulario")
