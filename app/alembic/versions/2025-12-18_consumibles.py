"""consumibles

Crea el inventario por cantidad (consumibles) y su bitácora de movimientos
de stock (entrada/salida/ajuste).

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2025-12-18 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "INV_CONSUMIBLE",
        sa.Column("CON_Consumible", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("CON_Nombre", sa.String(length=100), nullable=False),
        sa.Column("CON_Descripcion", sa.String(length=255), nullable=True),
        sa.Column("CON_Categoria", sa.String(length=50), nullable=True),
        sa.Column("CON_Unidad", sa.String(length=20), nullable=False, server_default="unidad"),
        sa.Column("CON_Stock_Actual", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("CON_Stock_Minimo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("CON_Activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("CON_Consumible"),
        sa.UniqueConstraint("CON_Nombre", name="uq_consumible_nombre"),
        sa.CheckConstraint('"CON_Stock_Actual" >= 0', name="ck_consumible_stock_no_negativo"),
        sa.CheckConstraint('"CON_Stock_Minimo" >= 0', name="ck_consumible_minimo_no_negativo"),
    )
    op.create_index("ix_INV_CONSUMIBLE_CON_Consumible", "INV_CONSUMIBLE", ["CON_Consumible"])

    op.create_table(
        "INV_MOVIMIENTO_CONSUMIBLE",
        sa.Column("MOC_Movimiento", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("MOC_Tipo", sa.String(length=10), nullable=False),
        sa.Column("MOC_Cantidad", sa.Integer(), nullable=False),
        sa.Column("MOC_Stock_Resultante", sa.Integer(), nullable=False),
        sa.Column("MOC_Motivo", sa.String(length=255), nullable=True),
        sa.Column("MOC_Fecha", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("CON_Consumible", sa.Integer(), nullable=False),
        sa.Column("PER_Persona", sa.Uuid(), nullable=True),
        sa.Column("USU_Usuario", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("MOC_Movimiento"),
        sa.ForeignKeyConstraint(["CON_Consumible"], ["INV_CONSUMIBLE.CON_Consumible"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["PER_Persona"], ["INV_PERSONA.PER_Persona"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["USU_Usuario"], ["INV_USUARIO.USU_Usuario"], ondelete="SET NULL"),
        sa.CheckConstraint('"MOC_Cantidad" > 0', name="ck_moc_cantidad_positiva"),
        sa.CheckConstraint("\"MOC_Tipo\" IN ('ENTRADA', 'SALIDA', 'AJUSTE')", name="ck_moc_tipo_valido"),
    )
    op.create_index("ix_INV_MOVIMIENTO_CONSUMIBLE_MOC_Movimiento", "INV_MOVIMIENTO_CONSUMIBLE", ["MOC_Movimiento"])
    op.create_index("ix_moc_consumible", "INV_MOVIMIENTO_CONSUMIBLE", ["CON_Consumible"])
    op.create_index("ix_moc_fecha", "INV_MOVIMIENTO_CONSUMIBLE", ["MOC_Fecha"])


def downgrade() -> None:
    op.drop_table("INV_MOVIMIENTO_CONSUMIBLE")
    op.drop_table("INV_CONSUMIBLE")
