"""Cuenta de servicio genérica para correo y Active Directory (configurable desde la UI).

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "SYS_INTEGRACION_CORREO",
        sa.Column("INT_Id", sa.Integer(), primary_key=True),
        sa.Column("INT_Modo", sa.String(12), nullable=False, server_default="DESACTIVADO"),
        sa.Column("INT_Proveedor", sa.String(10), nullable=False, server_default="SMTP"),
        sa.Column("INT_Cuenta_Email", sa.String(150)),
        sa.Column("INT_Cuenta_Usuario", sa.String(150)),
        sa.Column("INT_Cuenta_Password_Enc", sa.String(1000)),
        sa.Column("INT_Nombre_Remitente", sa.String(100)),
        sa.Column("INT_SMTP_Host", sa.String(150)),
        sa.Column("INT_SMTP_Puerto", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("INT_SMTP_Seguridad", sa.String(10), nullable=False, server_default="STARTTLS"),
        sa.Column("INT_Graph_Tenant_Id", sa.String(100)),
        sa.Column("INT_Graph_Client_Id", sa.String(100)),
        sa.Column("INT_Graph_Secret_Enc", sa.String(1000)),
        sa.Column("INT_AD_Servidor", sa.String(300)),
        sa.Column("INT_AD_Base_DN", sa.String(300)),
        sa.Column("INT_AD_Grupo_Base_DN", sa.String(300)),
        sa.Column("INT_AD_Grupo_Admin", sa.String(150)),
        sa.Column("INT_AD_Start_TLS", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("INT_AD_Verificar_Cert", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("INT_AD_Intervalo_Min", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("INT_AD_Desactivar", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("INT_AD_Usar_Cuenta_Servicio", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("INT_AD_Bind_Usuario", sa.String(150)),
        sa.Column("INT_AD_Bind_Password_Enc", sa.String(1000)),
        sa.Column("INT_Actualizado_En", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("USU_Actualizado_Por", sa.Uuid()),
        sa.CheckConstraint("\"INT_Id\" = 1", name="ck_integracion_fila_unica"),
        sa.CheckConstraint("\"INT_Modo\" IN ('DESACTIVADO','CORREO','CORREO_AD')", name="ck_integracion_modo"),
        sa.CheckConstraint("\"INT_Proveedor\" IN ('SMTP','GRAPH')", name="ck_integracion_proveedor"),
        sa.CheckConstraint("\"INT_SMTP_Seguridad\" IN ('STARTTLS','SSL','NINGUNA')", name="ck_integracion_smtp_seguridad"),
    )


def downgrade() -> None:
    op.drop_table("SYS_INTEGRACION_CORREO")
