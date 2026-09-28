"""Moneda por registro en activos y mantenimientos.

Hasta ahora solo las órdenes de compra tenían moneda; el costo de un activo y
el de un mantenimiento se asumían en quetzales. Ahora cada monto guarda la
moneda en que se pagó (GTQ, USD o CHF) y no se convierte.

- INV_ACTIVO.ACT_Moneda: los activos que llegaron por una orden de compra
  toman la moneda de esa orden; el resto queda en GTQ (lo que ya se asumía).
- INV_MANTENIMIENTO.MAN_Moneda: todos quedan en GTQ.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-09-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MONEDAS = "'GTQ', 'USD', 'CHF'"


def upgrade() -> None:
    with op.batch_alter_table("INV_ACTIVO") as batch:
        batch.add_column(sa.Column(
            "ACT_Moneda", sa.String(3), nullable=False, server_default="GTQ",
        ))
        batch.create_check_constraint(
            "ck_activo_moneda_valida", f'"ACT_Moneda" IN ({_MONEDAS})',
        )

    with op.batch_alter_table("INV_MANTENIMIENTO") as batch:
        batch.add_column(sa.Column(
            "MAN_Moneda", sa.String(3), nullable=False, server_default="GTQ",
        ))
        batch.create_check_constraint(
            "ck_mantenimiento_moneda_valida", f'"MAN_Moneda" IN ({_MONEDAS})',
        )

    # Activos recibidos por una orden: su costo salió del precio de la línea,
    # que está en la moneda de la orden. El enlace está en la tabla de lote
    # y, en órdenes antiguas, directamente en la línea.
    op.execute(
        """
        UPDATE "INV_ACTIVO" a
           SET "ACT_Moneda" = src."OCO_Moneda"
          FROM (
                SELECT la."ACT_Activo", o."OCO_Moneda"
                  FROM "INV_ORDEN_COMPRA_LINEA_ACTIVO" la
                  JOIN "INV_ORDEN_COMPRA_LINEA" l ON l."OCL_Linea" = la."OCL_Linea"
                  JOIN "INV_ORDEN_COMPRA" o ON o."OCO_Orden" = l."OCO_Orden"
                UNION
                SELECT l."ACT_Activo", o."OCO_Moneda"
                  FROM "INV_ORDEN_COMPRA_LINEA" l
                  JOIN "INV_ORDEN_COMPRA" o ON o."OCO_Orden" = l."OCO_Orden"
                 WHERE l."ACT_Activo" IS NOT NULL
               ) src
         WHERE src."ACT_Activo" = a."ACT_Activo"
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("INV_MANTENIMIENTO") as batch:
        batch.drop_constraint("ck_mantenimiento_moneda_valida", type_="check")
        batch.drop_column("MAN_Moneda")
    with op.batch_alter_table("INV_ACTIVO") as batch:
        batch.drop_constraint("ck_activo_moneda_valida", type_="check")
        batch.drop_column("ACT_Moneda")
