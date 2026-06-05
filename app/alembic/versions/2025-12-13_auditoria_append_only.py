"""auditoria_append_only

Convierte INV_AUDITORIA_SISTEMA en append-only (forense): un trigger en
Postgres rechaza cualquier UPDATE o DELETE sobre la bitácora. Las filas solo
se pueden INSERTAR. Esto evita que un backend comprometido o un operador con
acceso a la BD reescriba la historia sin dejar rastro.

La purga por retención (si se implementa) debe hacerse con un rol de BD
distinto y privilegiado que primero deshabilite el trigger (ALTER TABLE ...
DISABLE TRIGGER), o exportando a almacenamiento WORM/SIEM externo.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2025-12-13 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, Sequence[str], None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # El trigger es específico de Postgres; en otros motores se omite.
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION inv_auditoria_append_only()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'INV_AUDITORIA_SISTEMA es append-only: % no permitido', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_auditoria_append_only ON \"INV_AUDITORIA_SISTEMA\";")
    op.execute(
        """
        CREATE TRIGGER trg_auditoria_append_only
        BEFORE UPDATE OR DELETE ON "INV_AUDITORIA_SISTEMA"
        FOR EACH ROW EXECUTE FUNCTION inv_auditoria_append_only();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_auditoria_append_only ON \"INV_AUDITORIA_SISTEMA\";")
    op.execute("DROP FUNCTION IF EXISTS inv_auditoria_append_only();")
