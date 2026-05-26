"""token_revocado

Tabla de blacklist para JTI revocados (logout, password change).

Revision ID: a3b4c5d6e7f8
Revises: f2b3c4d5e6f7
Create Date: 2025-12-10 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "SYS_TOKEN_REVOCADO",
        sa.Column("TRV_Jti", sa.String(length=64), primary_key=True),
        sa.Column("TRV_Tipo", sa.String(length=10), nullable=False),
        sa.Column(
            "TRV_Fecha_Revocacion",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("TRV_Expira", sa.DateTime(), nullable=False),
        sa.Column("USU_Usuario", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["USU_Usuario"], ["INV_USUARIO.USU_Usuario"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_token_revocado_expira", "SYS_TOKEN_REVOCADO", ["TRV_Expira"]
    )
    op.create_index(
        "ix_token_revocado_usuario", "SYS_TOKEN_REVOCADO", ["USU_Usuario"]
    )


def downgrade() -> None:
    op.drop_index("ix_token_revocado_usuario", table_name="SYS_TOKEN_REVOCADO")
    op.drop_index("ix_token_revocado_expira", table_name="SYS_TOKEN_REVOCADO")
    op.drop_table("SYS_TOKEN_REVOCADO")
