"""compras

Crea Proveedores, Órdenes de Compra y sus líneas. Las líneas enlazan
opcionalmente a un activo o consumible (alimenta la vista de garantías).

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2025-12-20 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "INV_PROVEEDOR",
        sa.Column("PRV_Proveedor", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("PRV_Nombre", sa.String(length=150), nullable=False),
        sa.Column("PRV_Identificacion_Fiscal", sa.String(length=50), nullable=True),
        sa.Column("PRV_Contacto", sa.String(length=100), nullable=True),
        sa.Column("PRV_Email", sa.String(length=150), nullable=True),
        sa.Column("PRV_Telefono", sa.String(length=30), nullable=True),
        sa.Column("PRV_Direccion", sa.String(length=255), nullable=True),
        sa.Column("PRV_Activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("PRV_Proveedor"),
        sa.UniqueConstraint("PRV_Nombre", name="uq_proveedor_nombre"),
    )
    op.create_index("ix_INV_PROVEEDOR_PRV_Proveedor", "INV_PROVEEDOR", ["PRV_Proveedor"])

    op.create_table(
        "INV_ORDEN_COMPRA",
        sa.Column("OCO_Orden", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("OCO_Numero", sa.String(length=50), nullable=False),
        sa.Column("OCO_Fecha", sa.Date(), nullable=False),
        sa.Column("OCO_Estado", sa.String(length=15), nullable=False, server_default="BORRADOR"),
        sa.Column("OCO_Moneda", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("OCO_Total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("OCO_Notas", sa.String(length=500), nullable=True),
        sa.Column("PRV_Proveedor", sa.Integer(), nullable=False),
        sa.Column("USU_Usuario", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("OCO_Orden"),
        sa.UniqueConstraint("OCO_Numero", name="uq_orden_numero"),
        sa.ForeignKeyConstraint(["PRV_Proveedor"], ["INV_PROVEEDOR.PRV_Proveedor"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["USU_Usuario"], ["INV_USUARIO.USU_Usuario"], ondelete="SET NULL"),
        sa.CheckConstraint("\"OCO_Estado\" IN ('BORRADOR', 'RECIBIDA', 'CANCELADA')", name="ck_orden_estado_valido"),
        sa.CheckConstraint('"OCO_Total" >= 0', name="ck_orden_total_no_negativo"),
    )
    op.create_index("ix_INV_ORDEN_COMPRA_OCO_Orden", "INV_ORDEN_COMPRA", ["OCO_Orden"])
    op.create_index("ix_orden_proveedor", "INV_ORDEN_COMPRA", ["PRV_Proveedor"])

    op.create_table(
        "INV_ORDEN_COMPRA_LINEA",
        sa.Column("OCL_Linea", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("OCL_Descripcion", sa.String(length=255), nullable=False),
        sa.Column("OCL_Cantidad", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("OCL_Precio_Unitario", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("OCL_Subtotal", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("OCO_Orden", sa.Integer(), nullable=False),
        sa.Column("ACT_Activo", sa.Uuid(), nullable=True),
        sa.Column("CON_Consumible", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("OCL_Linea"),
        sa.ForeignKeyConstraint(["OCO_Orden"], ["INV_ORDEN_COMPRA.OCO_Orden"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ACT_Activo"], ["INV_ACTIVO.ACT_Activo"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["CON_Consumible"], ["INV_CONSUMIBLE.CON_Consumible"], ondelete="SET NULL"),
        sa.CheckConstraint('"OCL_Cantidad" > 0', name="ck_linea_cantidad_positiva"),
        sa.CheckConstraint('"OCL_Precio_Unitario" >= 0', name="ck_linea_precio_no_negativo"),
    )
    op.create_index("ix_INV_ORDEN_COMPRA_LINEA_OCL_Linea", "INV_ORDEN_COMPRA_LINEA", ["OCL_Linea"])
    op.create_index("ix_linea_orden", "INV_ORDEN_COMPRA_LINEA", ["OCO_Orden"])
    op.create_index("ix_linea_activo", "INV_ORDEN_COMPRA_LINEA", ["ACT_Activo"])


def downgrade() -> None:
    op.drop_table("INV_ORDEN_COMPRA_LINEA")
    op.drop_table("INV_ORDEN_COMPRA")
    op.drop_table("INV_PROVEEDOR")
