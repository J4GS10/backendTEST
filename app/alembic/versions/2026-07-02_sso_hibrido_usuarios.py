"""sso_hibrido_usuarios

Permite usuarios con password interna, SSO o ambos.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-07-02 00:10:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("INV_USUARIO") as batch:
        batch.alter_column("USU_Password_Hash", existing_type=sa.String(length=255), nullable=True)
        batch.add_column(sa.Column("USU_SSO_Habilitado", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("USU_SSO_Provider", sa.String(length=20), nullable=True))
        batch.create_check_constraint(
            "ck_usuario_sso_provider_valido",
            "\"USU_SSO_Provider\" IS NULL OR \"USU_SSO_Provider\" IN ('microsoft', 'google')",
        )
    with op.batch_alter_table("INV_USUARIO") as batch:
        batch.alter_column("USU_SSO_Habilitado", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("INV_USUARIO") as batch:
        batch.drop_constraint("ck_usuario_sso_provider_valido", type_="check")
        batch.drop_column("USU_SSO_Provider")
        batch.drop_column("USU_SSO_Habilitado")
        batch.alter_column("USU_Password_Hash", existing_type=sa.String(length=255), nullable=False)
