"""adjuntos

Crea INV_ADJUNTO: metadatos de archivos asociados a un activo (factura, foto,
acta firmada). Los bytes viven en disco; aquí solo la referencia.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2025-12-19 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "INV_ADJUNTO",
        sa.Column("ADJ_Adjunto", sa.Uuid(), nullable=False),
        sa.Column("ADJ_Nombre_Original", sa.String(length=255), nullable=False),
        sa.Column("ADJ_Nombre_Almacenado", sa.String(length=255), nullable=False),
        sa.Column("ADJ_Tipo_MIME", sa.String(length=120), nullable=True),
        sa.Column("ADJ_Tamano_Bytes", sa.Integer(), nullable=False),
        sa.Column("ADJ_Categoria", sa.String(length=20), nullable=False, server_default="otro"),
        sa.Column("ADJ_Descripcion", sa.String(length=255), nullable=True),
        sa.Column("ADJ_Fecha_Subida", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("ACT_Activo", sa.Uuid(), nullable=False),
        sa.Column("USU_Usuario", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("ADJ_Adjunto"),
        sa.ForeignKeyConstraint(["ACT_Activo"], ["INV_ACTIVO.ACT_Activo"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["USU_Usuario"], ["INV_USUARIO.USU_Usuario"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "\"ADJ_Categoria\" IN ('factura', 'foto', 'acta', 'otro')",
            name="ck_adjunto_categoria_valida",
        ),
        sa.CheckConstraint('"ADJ_Tamano_Bytes" >= 0', name="ck_adjunto_tamano_no_negativo"),
    )
    op.create_index("ix_INV_ADJUNTO_ADJ_Adjunto", "INV_ADJUNTO", ["ADJ_Adjunto"])
    op.create_index("ix_adjunto_activo", "INV_ADJUNTO", ["ACT_Activo"])
    op.create_index("ix_adjunto_fecha", "INV_ADJUNTO", ["ADJ_Fecha_Subida"])


def downgrade() -> None:
    op.drop_table("INV_ADJUNTO")
