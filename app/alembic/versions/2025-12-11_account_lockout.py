"""account_lockout

Columnas para tracking de intentos fallidos y bloqueo temporal de cuenta.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2025-12-11 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "INV_USUARIO",
        sa.Column("USU_Intentos_Fallidos", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "INV_USUARIO",
        sa.Column("USU_Bloqueado_Hasta", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "INV_USUARIO",
        sa.Column("USU_Password_Cambiada_En", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("INV_USUARIO", "USU_Password_Cambiada_En")
    op.drop_column("INV_USUARIO", "USU_Bloqueado_Hasta")
    op.drop_column("INV_USUARIO", "USU_Intentos_Fallidos")
