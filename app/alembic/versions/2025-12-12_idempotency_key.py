"""idempotency_key

Tabla de cache para soportar cabecera 'Idempotency-Key' en operaciones POST.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2025-12-12 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "SYS_IDEMPOTENCY_KEY",
        sa.Column("IDK_Key", sa.String(length=128), primary_key=True),
        sa.Column("IDK_Endpoint", sa.String(length=200), nullable=False),
        sa.Column("IDK_Usuario", sa.UUID(), nullable=False),
        sa.Column("IDK_Request_Hash", sa.String(length=64), nullable=False),
        sa.Column("IDK_Response_Status", sa.Integer(), nullable=False),
        sa.Column("IDK_Response_Body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "IDK_Creada_En",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["IDK_Usuario"], ["INV_USUARIO.USU_Usuario"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_idempotency_usuario", "SYS_IDEMPOTENCY_KEY", ["IDK_Usuario"]
    )
    op.create_index(
        "ix_idempotency_creada", "SYS_IDEMPOTENCY_KEY", ["IDK_Creada_En"]
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_creada", table_name="SYS_IDEMPOTENCY_KEY")
    op.drop_index("ix_idempotency_usuario", table_name="SYS_IDEMPOTENCY_KEY")
    op.drop_table("SYS_IDEMPOTENCY_KEY")
