"""compras lotes y licencias individuales

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-07-03 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "INV_ORDEN_COMPRA",
        "OCO_Moneda",
        existing_type=sa.String(length=3),
        server_default="GTQ",
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_orden_moneda_valida",
        "INV_ORDEN_COMPRA",
        "\"OCO_Moneda\" IN ('GTQ', 'USD', 'CHF')",
    )

    op.add_column(
        "INV_ORDEN_COMPRA_LINEA",
        sa.Column("LIC_Licencia", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_linea_licencia",
        "INV_ORDEN_COMPRA_LINEA",
        "INV_LICENCIA",
        ["LIC_Licencia"],
        ["LIC_Licencia"],
        ondelete="SET NULL",
    )
    op.create_index("ix_linea_licencia", "INV_ORDEN_COMPRA_LINEA", ["LIC_Licencia"])

    op.create_table(
        "INV_ORDEN_COMPRA_LINEA_ACTIVO",
        sa.Column("OLA_Orden_Linea_Activo", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("OCL_Linea", sa.Integer(), nullable=False),
        sa.Column("ACT_Activo", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("OLA_Orden_Linea_Activo"),
        sa.ForeignKeyConstraint(["OCL_Linea"], ["INV_ORDEN_COMPRA_LINEA.OCL_Linea"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ACT_Activo"], ["INV_ACTIVO.ACT_Activo"], ondelete="RESTRICT"),
        sa.UniqueConstraint("ACT_Activo", name="uq_orden_linea_activo_activo"),
    )
    op.create_index(
        "ix_INV_ORDEN_COMPRA_LINEA_ACTIVO_OLA_Orden_Linea_Activo",
        "INV_ORDEN_COMPRA_LINEA_ACTIVO",
        ["OLA_Orden_Linea_Activo"],
    )
    op.create_index("ix_ola_linea", "INV_ORDEN_COMPRA_LINEA_ACTIVO", ["OCL_Linea"])
    op.create_index("ix_ola_activo", "INV_ORDEN_COMPRA_LINEA_ACTIVO", ["ACT_Activo"])

    op.create_table(
        "INV_LICENCIA_CLAVE",
        sa.Column("LCL_Licencia_Clave", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("LIC_Licencia", sa.Integer(), nullable=False),
        sa.Column("LCL_Clave_Activacion", sa.String(length=1000), nullable=False),
        sa.Column("LCL_Clave_Hash", sa.String(length=64), nullable=False),
        sa.Column("LCL_Referencia", sa.String(length=120), nullable=True),
        sa.Column("LCL_Estado", sa.String(length=20), nullable=False, server_default="DISPONIBLE"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("LCL_Licencia_Clave"),
        sa.ForeignKeyConstraint(["LIC_Licencia"], ["INV_LICENCIA.LIC_Licencia"], ondelete="CASCADE"),
        sa.UniqueConstraint("LCL_Clave_Hash", name="uq_licencia_clave_hash"),
        sa.CheckConstraint(
            "\"LCL_Estado\" IN ('DISPONIBLE', 'ASIGNADA', 'RETIRADA')",
            name="ck_licencia_clave_estado_valido",
        ),
    )
    op.create_index("ix_INV_LICENCIA_CLAVE_LCL_Licencia_Clave", "INV_LICENCIA_CLAVE", ["LCL_Licencia_Clave"])
    op.create_index("ix_licencia_clave_licencia", "INV_LICENCIA_CLAVE", ["LIC_Licencia"])

    op.add_column(
        "INV_INSTALACION",
        sa.Column("LCL_Licencia_Clave", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_instalacion_licencia_clave",
        "INV_INSTALACION",
        "INV_LICENCIA_CLAVE",
        ["LCL_Licencia_Clave"],
        ["LCL_Licencia_Clave"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_instalacion_clave_activa",
        "INV_INSTALACION",
        ["LCL_Licencia_Clave"],
        unique=True,
        postgresql_where=sa.text('"INS_Estado" IS TRUE AND "LCL_Licencia_Clave" IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index("uq_instalacion_clave_activa", table_name="INV_INSTALACION")
    op.drop_constraint("fk_instalacion_licencia_clave", "INV_INSTALACION", type_="foreignkey")
    op.drop_column("INV_INSTALACION", "LCL_Licencia_Clave")

    op.drop_index("ix_licencia_clave_licencia", table_name="INV_LICENCIA_CLAVE")
    op.drop_index("ix_INV_LICENCIA_CLAVE_LCL_Licencia_Clave", table_name="INV_LICENCIA_CLAVE")
    op.drop_table("INV_LICENCIA_CLAVE")

    op.drop_index("ix_ola_activo", table_name="INV_ORDEN_COMPRA_LINEA_ACTIVO")
    op.drop_index("ix_ola_linea", table_name="INV_ORDEN_COMPRA_LINEA_ACTIVO")
    op.drop_index(
        "ix_INV_ORDEN_COMPRA_LINEA_ACTIVO_OLA_Orden_Linea_Activo",
        table_name="INV_ORDEN_COMPRA_LINEA_ACTIVO",
    )
    op.drop_table("INV_ORDEN_COMPRA_LINEA_ACTIVO")

    op.drop_index("ix_linea_licencia", table_name="INV_ORDEN_COMPRA_LINEA")
    op.drop_constraint("fk_linea_licencia", "INV_ORDEN_COMPRA_LINEA", type_="foreignkey")
    op.drop_column("INV_ORDEN_COMPRA_LINEA", "LIC_Licencia")

    op.drop_constraint("ck_orden_moneda_valida", "INV_ORDEN_COMPRA", type_="check")
    op.alter_column(
        "INV_ORDEN_COMPRA",
        "OCO_Moneda",
        existing_type=sa.String(length=3),
        server_default="USD",
        existing_nullable=False,
    )
