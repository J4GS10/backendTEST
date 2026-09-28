"""instalacion_persona_y_etiquetas

Permite asignar licencias a un activo fisico o directamente a una persona
(XOR), con indices unicos parciales para impedir duplicados activos.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-07-02 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("INV_INSTALACION") as batch:
        batch.alter_column("ACT_Activo", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("PER_Persona", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_instalacion_persona",
            "INV_PERSONA",
            ["PER_Persona"],
            ["PER_Persona"],
            ondelete="CASCADE",
        )
        batch.create_check_constraint(
            "ck_instalacion_destino_xor",
            '("ACT_Activo" IS NOT NULL AND "PER_Persona" IS NULL) '
            'OR ("ACT_Activo" IS NULL AND "PER_Persona" IS NOT NULL)',
        )

    op.create_index(
        "uq_instalacion_activo_licencia_activa",
        "INV_INSTALACION",
        ["ACT_Activo", "LIC_Licencia"],
        unique=True,
        postgresql_where=sa.text('"INS_Estado" = true AND "ACT_Activo" IS NOT NULL'),
        sqlite_where=sa.text('"INS_Estado" = 1 AND "ACT_Activo" IS NOT NULL'),
    )
    op.create_index(
        "uq_instalacion_persona_licencia_activa",
        "INV_INSTALACION",
        ["PER_Persona", "LIC_Licencia"],
        unique=True,
        postgresql_where=sa.text('"INS_Estado" = true AND "PER_Persona" IS NOT NULL'),
        sqlite_where=sa.text('"INS_Estado" = 1 AND "PER_Persona" IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index("uq_instalacion_persona_licencia_activa", table_name="INV_INSTALACION")
    op.drop_index("uq_instalacion_activo_licencia_activa", table_name="INV_INSTALACION")
    with op.batch_alter_table("INV_INSTALACION") as batch:
        batch.drop_constraint("ck_instalacion_destino_xor", type_="check")
        batch.drop_constraint("fk_instalacion_persona", type_="foreignkey")
        batch.drop_column("PER_Persona")
        batch.alter_column("ACT_Activo", existing_type=sa.Uuid(), nullable=False)
