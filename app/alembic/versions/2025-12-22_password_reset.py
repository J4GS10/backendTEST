"""password_reset

Crea SYS_PASSWORD_RESET: tokens de restablecimiento de contraseña (hash,
expiración, un solo uso) para el flujo "olvidé mi contraseña".

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2025-12-22 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "SYS_PASSWORD_RESET",
        sa.Column("PRT_Id", sa.Uuid(), nullable=False),
        sa.Column("PRT_Token_Hash", sa.String(length=64), nullable=False),
        sa.Column("PRT_Expira", sa.DateTime(), nullable=False),
        sa.Column("PRT_Usado", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("PRT_Creado_En", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("USU_Usuario", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("PRT_Id"),
        sa.UniqueConstraint("PRT_Token_Hash", name="uq_reset_token_hash"),
        sa.ForeignKeyConstraint(["USU_Usuario"], ["INV_USUARIO.USU_Usuario"], ondelete="CASCADE"),
    )
    op.create_index("ix_reset_token_hash", "SYS_PASSWORD_RESET", ["PRT_Token_Hash"])
    op.create_index("ix_reset_expira", "SYS_PASSWORD_RESET", ["PRT_Expira"])
    op.create_index("ix_reset_usuario", "SYS_PASSWORD_RESET", ["USU_Usuario"])


def downgrade() -> None:
    op.drop_table("SYS_PASSWORD_RESET")
