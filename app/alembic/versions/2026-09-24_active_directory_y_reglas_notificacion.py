"""Active Directory: vínculo AD y jefe en personas + reglas de notificación.

También fusiona los dos heads existentes (b2c3d4e5f607 idempotency y
b9c8d7e6f5a4 performance indexes), que colgaban ambos de a1b2c3d4e5f6.

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f607, b9c8d7e6f5a4
Create Date: 2026-09-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = ("b2c3d4e5f607", "b9c8d7e6f5a4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("INV_PERSONA") as batch:
        batch.add_column(sa.Column("PER_Jefe", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("PER_AD_GUID", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("PER_AD_DN", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("PER_AD_Sincronizado_En", sa.DateTime(), nullable=True))
        batch.create_foreign_key(
            "fk_persona_jefe", "INV_PERSONA", ["PER_Jefe"], ["PER_Persona"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_INV_PERSONA_PER_Jefe", ["PER_Jefe"])
        batch.create_index("ix_INV_PERSONA_PER_AD_GUID", ["PER_AD_GUID"], unique=True)

    op.create_table(
        "INV_REGLA_NOTIFICACION",
        sa.Column("RNO_Evento", sa.String(length=50), primary_key=True),
        sa.Column("RNO_Activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("RNO_Notificar_Afectado", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("RNO_Notificar_Jefe", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("RNO_Copiar_Admins", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("RNO_Grupos_AD", sa.String(length=1000), nullable=True),
        sa.Column("RNO_Correos_Extra", sa.String(length=1000), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("INV_REGLA_NOTIFICACION")
    with op.batch_alter_table("INV_PERSONA") as batch:
        batch.drop_index("ix_INV_PERSONA_PER_AD_GUID")
        batch.drop_index("ix_INV_PERSONA_PER_Jefe")
        batch.drop_constraint("fk_persona_jefe", type_="foreignkey")
        batch.drop_column("PER_AD_Sincronizado_En")
        batch.drop_column("PER_AD_DN")
        batch.drop_column("PER_AD_GUID")
        batch.drop_column("PER_Jefe")
