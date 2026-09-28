"""Oracle 21c schema baseline with equivalent conditional invariants."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Sequence, Union

from alembic import op

from app.db.base import Base
import app.models.attachment  # noqa: F401
import app.models.consumable  # noqa: F401
import app.models.procurement  # noqa: F401

revision: str = "oracle21c_baseline_20260731"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = ("oracle",)
depends_on: Union[str, Sequence[str], None] = None


@contextmanager
def _without_postgres_partial_indexes() -> Iterator[None]:
    indexes = [
        index
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if index.dialect_options["postgresql"].get("where") is not None
    ]
    for index in indexes:
        index.table.indexes.remove(index)
    try:
        yield
    finally:
        for index in indexes:
            index.table.indexes.add(index)


def upgrade() -> None:
    bind = op.get_bind()
    with _without_postgres_partial_indexes():
        Base.metadata.create_all(bind=bind)

    # SQLAlchemy's Oracle dialect has no native generic JSON type. PortableJSON
    # stores documents in CLOB columns; Oracle 21c validates their contents.
    op.execute(
        'ALTER TABLE "INV_AUDITORIA_SISTEMA" ADD CONSTRAINT ck_aud_snapshot_json '
        'CHECK ("AUD_Snapshot_JSON" IS JSON)'
    )
    op.execute(
        'ALTER TABLE "SYS_IDEMPOTENCY_KEY" ADD CONSTRAINT ck_idk_response_json '
        'CHECK ("IDK_Response_Body" IS JSON)'
    )

    # Oracle 21c has no partial indexes. These function-based unique indexes
    # preserve the PostgreSQL invariant only for rows considered active/open.
    op.execute(
        'CREATE UNIQUE INDEX uq_movimiento_activo_abierto ON "INV_MOVIMIENTO" '
        '(CASE WHEN "MOV_Fecha_Devolucion" IS NULL THEN "ACT_Activo" END)'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_mantenimiento_activo_abierto ON "INV_MANTENIMIENTO" '
        '(CASE WHEN "MAN_Fecha_Cierre" IS NULL THEN "ACT_Activo" END)'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_instalacion_activo_licencia_activa ON "INV_INSTALACION" '
        '(CASE WHEN "INS_Estado" = 1 THEN "ACT_Activo" END, '
        'CASE WHEN "INS_Estado" = 1 THEN "LIC_Licencia" END)'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_instalacion_persona_licencia_activa ON "INV_INSTALACION" '
        '(CASE WHEN "INS_Estado" = 1 THEN "PER_Persona" END, '
        'CASE WHEN "INS_Estado" = 1 THEN "LIC_Licencia" END)'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_instalacion_clave_activa ON "INV_INSTALACION" '
        '(CASE WHEN "INS_Estado" = 1 THEN "LCL_Licencia_Clave" END)'
    )
    op.execute(
        'CREATE INDEX ix_movimiento_activo_vigente ON "INV_MOVIMIENTO" '
        '(CASE WHEN "MOV_Fecha_Devolucion" IS NULL THEN "ACT_Activo" END)'
    )
    op.execute(
        'CREATE INDEX ix_instalacion_activa ON "INV_INSTALACION" '
        '(CASE WHEN "INS_Estado" = 1 THEN "ACT_Activo" END)'
    )
    op.execute(
        '''CREATE OR REPLACE TRIGGER trg_auditoria_append_only
        BEFORE UPDATE OR DELETE ON "INV_AUDITORIA_SISTEMA"
        FOR EACH ROW
        BEGIN
            RAISE_APPLICATION_ERROR(-20001, 'INV_AUDITORIA_SISTEMA is append-only');
        END;'''
    )


def downgrade() -> None:
    op.execute('DROP TRIGGER trg_auditoria_append_only')
    for index in (
        "ix_instalacion_activa",
        "ix_movimiento_activo_vigente",
        "uq_instalacion_clave_activa",
        "uq_instalacion_persona_licencia_activa",
        "uq_instalacion_activo_licencia_activa",
        "uq_mantenimiento_activo_abierto",
        "uq_movimiento_activo_abierto",
    ):
        op.execute(f'DROP INDEX {index}')
    op.execute('ALTER TABLE "SYS_IDEMPOTENCY_KEY" DROP CONSTRAINT ck_idk_response_json')
    op.execute('ALTER TABLE "INV_AUDITORIA_SISTEMA" DROP CONSTRAINT ck_aud_snapshot_json')
    Base.metadata.drop_all(bind=op.get_bind())
