"""Cola persistente de correos + índices faltantes de SYS_TOKEN_REVOCADO.

- SYS_EMAIL_OUTBOX: outbox drenado por el worker (SKIP LOCKED + backoff).
- ix_SYS_TOKEN_REVOCADO_TRV_Expira / _USU_Usuario: declarados en el modelo
  pero nunca creados por una migración (detectado con `alembic check`). Los
  usan la purga periódica y la revocación global por usuario.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.types import PortableJSON

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "SYS_EMAIL_OUTBOX",
        sa.Column("EOB_Id", sa.Uuid(), primary_key=True),
        sa.Column("EOB_Plantilla", sa.String(length=50), nullable=False),
        sa.Column("EOB_Asunto", sa.String(length=255), nullable=False),
        sa.Column("EOB_Html", sa.Text(), nullable=False),
        sa.Column("EOB_Para", PortableJSON(), nullable=False),
        sa.Column("EOB_Afectados", PortableJSON(), nullable=True),
        sa.Column("EOB_Cc_Admins", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("EOB_Resolver", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("EOB_Reply_To", sa.String(length=150), nullable=True),
        sa.Column("EOB_Estado", sa.String(length=10), nullable=False, server_default="PENDIENTE"),
        sa.Column("EOB_Intentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("EOB_Proximo_Intento", sa.DateTime(), nullable=False),
        sa.Column("EOB_Ultimo_Error", sa.String(length=500), nullable=True),
        sa.Column("EOB_Creado_En", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("EOB_Enviado_En", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_email_outbox_pendientes", "SYS_EMAIL_OUTBOX", ["EOB_Estado", "EOB_Proximo_Intento"],
    )
    op.create_index("ix_SYS_TOKEN_REVOCADO_TRV_Expira", "SYS_TOKEN_REVOCADO", ["TRV_Expira"])
    op.create_index("ix_SYS_TOKEN_REVOCADO_USU_Usuario", "SYS_TOKEN_REVOCADO", ["USU_Usuario"])


def downgrade() -> None:
    op.drop_index("ix_SYS_TOKEN_REVOCADO_USU_Usuario", table_name="SYS_TOKEN_REVOCADO")
    op.drop_index("ix_SYS_TOKEN_REVOCADO_TRV_Expira", table_name="SYS_TOKEN_REVOCADO")
    op.drop_index("ix_email_outbox_pendientes", table_name="SYS_EMAIL_OUTBOX")
    op.drop_table("SYS_EMAIL_OUTBOX")
