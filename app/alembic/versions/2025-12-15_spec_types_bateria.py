"""spec_types_bateria

Agrega tipos de especificación comunes que faltaban (Batería, Salud de batería,
MAC, IMEI...) de forma idempotente. Los activos pueden tener RAM, Almacenamiento,
Procesador, etc. (ya sembrados) y ahora también lo relativo a baterías.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2025-12-15 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TIPOS = [
    ("Batería", "ciclos"),
    ("Salud de batería", "%"),
    ("Dirección MAC", None),
    ("Número de IMEI", None),
    ("Pulgadas de disco", '"'),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for nombre, unidad in _TIPOS:
        u = "NULL" if unidad is None else "'%s'" % unidad.replace("'", "''")
        op.execute(
            'INSERT INTO "INV_TIPO_ESPECIFICACION" ("TES_Nombre", "TES_Unidad_Medida") '
            "VALUES ('%s', %s) ON CONFLICT (\"TES_Nombre\") DO NOTHING;"
            % (nombre.replace("'", "''"), u)
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    nombres = ", ".join("'%s'" % n.replace("'", "''") for n, _ in _TIPOS)
    op.execute(f'DELETE FROM "INV_TIPO_ESPECIFICACION" WHERE "TES_Nombre" IN ({nombres});')
