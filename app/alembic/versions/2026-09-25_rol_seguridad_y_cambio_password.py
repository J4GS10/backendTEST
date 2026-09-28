"""Rol ADMIN_SEGURIDAD, contraseña temporal con cambio obligatorio y anti-replay TOTP.

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-09-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW = "\"USU_Rol\" IN ('SUPER_ADMIN', 'ADMIN_SEGURIDAD', 'ADMIN_TI', 'TECNICO', 'CONSULTA')"
_OLD = "\"USU_Rol\" IN ('SUPER_ADMIN', 'ADMIN_TI', 'TECNICO', 'CONSULTA')"


def upgrade() -> None:
    with op.batch_alter_table("INV_USUARIO") as batch:
        batch.add_column(sa.Column(
            "USU_Debe_Cambiar_Password", sa.Boolean(), nullable=False, server_default=sa.false(),
        ))
        batch.add_column(sa.Column("USU_2FA_Ultimo_Paso", sa.Integer(), nullable=True))
        batch.drop_constraint("ck_usuario_rol_valido", type_="check")
        batch.create_check_constraint("ck_usuario_rol_valido", _NEW)


def downgrade() -> None:
    op.execute("UPDATE \"INV_USUARIO\" SET \"USU_Rol\" = 'CONSULTA' WHERE \"USU_Rol\" = 'ADMIN_SEGURIDAD'")
    with op.batch_alter_table("INV_USUARIO") as batch:
        batch.drop_constraint("ck_usuario_rol_valido", type_="check")
        batch.create_check_constraint("ck_usuario_rol_valido", _OLD)
        batch.drop_column("USU_2FA_Ultimo_Paso")
        batch.drop_column("USU_Debe_Cambiar_Password")
