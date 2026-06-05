"""adjunto_orden

Generaliza INV_ADJUNTO para que un adjunto pertenezca a un activo O a una orden
de compra (XOR). Hace ACT_Activo nullable, agrega OCO_Orden + FK y el CHECK XOR.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2025-12-21 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("INV_ADJUNTO", "ACT_Activo", existing_type=sa.Uuid(), nullable=True)
    op.add_column("INV_ADJUNTO", sa.Column("OCO_Orden", sa.Integer(), nullable=True))
    op.create_index("ix_adjunto_orden", "INV_ADJUNTO", ["OCO_Orden"])
    op.create_foreign_key(
        "fk_adjunto_orden", "INV_ADJUNTO", "INV_ORDEN_COMPRA",
        ["OCO_Orden"], ["OCO_Orden"], ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_adjunto_un_solo_dueno", "INV_ADJUNTO",
        '("ACT_Activo" IS NOT NULL AND "OCO_Orden" IS NULL) '
        'OR ("ACT_Activo" IS NULL AND "OCO_Orden" IS NOT NULL)',
    )


def downgrade() -> None:
    op.drop_constraint("ck_adjunto_un_solo_dueno", "INV_ADJUNTO", type_="check")
    op.drop_constraint("fk_adjunto_orden", "INV_ADJUNTO", type_="foreignkey")
    op.drop_index("ix_adjunto_orden", table_name="INV_ADJUNTO")
    op.drop_column("INV_ADJUNTO", "OCO_Orden")
    op.alter_column("INV_ADJUNTO", "ACT_Activo", existing_type=sa.Uuid(), nullable=False)
