"""modelo_tipo_activo

Relaciona INV_MODELO con INV_TIPO_ACTIVO (columna nullable). Permite la cascada
de selección: al elegir un tipo (p.ej. Mouse) la UI muestra solo los modelos de
ese tipo. Los modelos existentes quedan con tipo NULL (compatibles con todo).

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2025-12-16 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, Sequence[str], None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("INV_MODELO", sa.Column("TAC_Tipo_Activo", sa.Integer(), nullable=True))
    op.create_index("ix_modelo_tipo_activo", "INV_MODELO", ["TAC_Tipo_Activo"])
    op.create_foreign_key(
        "fk_modelo_tipo_activo", "INV_MODELO", "INV_TIPO_ACTIVO",
        ["TAC_Tipo_Activo"], ["TAC_Tipo_Activo"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_modelo_tipo_activo", "INV_MODELO", type_="foreignkey")
    op.drop_index("ix_modelo_tipo_activo", table_name="INV_MODELO")
    op.drop_column("INV_MODELO", "TAC_Tipo_Activo")
