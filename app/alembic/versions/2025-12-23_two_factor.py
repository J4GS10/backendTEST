"""two_factor

2FA/MFA: columnas en INV_USUARIO (habilitado/método/secreto cifrado) y tablas
SYS_2FA_CODE (OTP de email) y SYS_2FA_RECOVERY (códigos de recuperación).

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2025-12-23 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, Sequence[str], None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("INV_USUARIO", sa.Column("USU_2FA_Habilitado", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("INV_USUARIO", sa.Column("USU_2FA_Metodo", sa.String(length=10), nullable=True))
    op.add_column("INV_USUARIO", sa.Column("USU_2FA_Secret", sa.String(length=255), nullable=True))
    op.create_check_constraint(
        "ck_usuario_2fa_metodo_valido", "INV_USUARIO",
        "\"USU_2FA_Metodo\" IS NULL OR \"USU_2FA_Metodo\" IN ('TOTP', 'EMAIL')",
    )

    op.create_table(
        "SYS_2FA_CODE",
        sa.Column("TFC_Id", sa.Uuid(), nullable=False),
        sa.Column("TFC_Code_Hash", sa.String(length=64), nullable=False),
        sa.Column("TFC_Expira", sa.DateTime(), nullable=False),
        sa.Column("TFC_Usado", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("TFC_Intentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("TFC_Creado_En", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("USU_Usuario", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("TFC_Id"),
        sa.ForeignKeyConstraint(["USU_Usuario"], ["INV_USUARIO.USU_Usuario"], ondelete="CASCADE"),
    )
    op.create_index("ix_2fa_code_hash", "SYS_2FA_CODE", ["TFC_Code_Hash"])
    op.create_index("ix_2fa_code_expira", "SYS_2FA_CODE", ["TFC_Expira"])
    op.create_index("ix_2fa_code_usuario", "SYS_2FA_CODE", ["USU_Usuario"])

    op.create_table(
        "SYS_2FA_RECOVERY",
        sa.Column("TRC_Id", sa.Uuid(), nullable=False),
        sa.Column("TRC_Code_Hash", sa.String(length=64), nullable=False),
        sa.Column("TRC_Usado", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("TRC_Creado_En", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("USU_Usuario", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("TRC_Id"),
        sa.ForeignKeyConstraint(["USU_Usuario"], ["INV_USUARIO.USU_Usuario"], ondelete="CASCADE"),
    )
    op.create_index("ix_2fa_recovery_hash", "SYS_2FA_RECOVERY", ["TRC_Code_Hash"])
    op.create_index("ix_2fa_recovery_usuario", "SYS_2FA_RECOVERY", ["USU_Usuario"])


def downgrade() -> None:
    op.drop_table("SYS_2FA_RECOVERY")
    op.drop_table("SYS_2FA_CODE")
    op.drop_constraint("ck_usuario_2fa_metodo_valido", "INV_USUARIO", type_="check")
    op.drop_column("INV_USUARIO", "USU_2FA_Secret")
    op.drop_column("INV_USUARIO", "USU_2FA_Metodo")
    op.drop_column("INV_USUARIO", "USU_2FA_Habilitado")
