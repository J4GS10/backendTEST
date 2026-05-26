"""endurecimiento_integridad

Añade CHECK constraints, UNIQUE parciales, ondelete=, índices y
elimina la columna USU_Salt (passlib embebe el salt en el hash).

IMPORTANTE: Postgres distingue mayúsculas/minúsculas en identificadores;
las columnas CamelCase deben envolverse en comillas dobles dentro de
expresiones SQL (CHECK constraints, índices parciales, etc.).

Revision ID: f1a2b3c4d5e6
Revises: e6094e1f8aee
Create Date: 2025-12-08 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e6094e1f8aee"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # =========================================================
    # 1. CHECK CONSTRAINTS
    # Todas las expresiones usan comillas dobles para preservar
    # CamelCase en Postgres.
    # =========================================================
    op.create_check_constraint(
        "ck_activo_garantia_posterior_compra",
        "INV_ACTIVO",
        '"ACT_Fin_Garantia" IS NULL OR "ACT_Fin_Garantia" >= "ACT_Fecha_Compra"',
    )
    op.create_check_constraint(
        "ck_activo_padre_distinto_self",
        "INV_ACTIVO",
        '"ACT_Activo_Padre" IS NULL OR "ACT_Activo_Padre" <> "ACT_Activo"',
    )
    op.create_check_constraint(
        "ck_activo_costo_no_negativo",
        "INV_ACTIVO",
        '"ACT_Costo" IS NULL OR "ACT_Costo" >= 0',
    )
    op.create_unique_constraint(
        "uq_activo_serie_fabricante", "INV_ACTIVO", ["ACT_Serie_Fabricante"]
    )

    op.create_check_constraint(
        "ck_licencia_total_positivo", "INV_LICENCIA", '"LIC_Cantidad_Total" > 0'
    )
    op.create_check_constraint(
        "ck_licencia_usada_valida",
        "INV_LICENCIA",
        '"LIC_Cantidad_Usada" >= 0 AND "LIC_Cantidad_Usada" <= "LIC_Cantidad_Total"',
    )
    op.alter_column(
        "INV_LICENCIA",
        "LIC_Clave_Activacion",
        existing_type=sa.String(length=255),
        type_=sa.String(length=500),
        existing_nullable=True,
    )

    op.create_check_constraint(
        "ck_movimiento_devolucion_posterior",
        "INV_MOVIMIENTO",
        '"MOV_Fecha_Devolucion" IS NULL OR "MOV_Fecha_Devolucion" >= "MOV_Fecha_Asignacion"',
    )

    op.create_check_constraint(
        "ck_mantenimiento_cierre_posterior",
        "INV_MANTENIMIENTO",
        '"MAN_Fecha_Cierre" IS NULL OR "MAN_Fecha_Cierre" >= "MAN_Fecha_Ingreso"',
    )
    op.create_check_constraint(
        "ck_mantenimiento_costo_no_negativo", "INV_MANTENIMIENTO", '"MAN_Costo_Total" >= 0'
    )
    op.alter_column(
        "INV_MANTENIMIENTO",
        "MAN_Costo_Total",
        existing_type=sa.Numeric(10, 2),
        type_=sa.Numeric(12, 2),
        existing_nullable=True,
        server_default="0",
    )

    op.create_check_constraint(
        "ck_detalle_costo_no_negativo", "INV_DETALLE_MANT", '"DMA_Costo_Item" >= 0'
    )
    op.alter_column(
        "INV_DETALLE_MANT",
        "DMA_Costo_Item",
        existing_type=sa.Numeric(10, 2),
        type_=sa.Numeric(12, 2),
        existing_nullable=True,
        server_default="0",
    )

    op.create_check_constraint(
        "ck_evidencia_xor_movimiento_mantenimiento",
        "INV_EVIDENCIA",
        '("MOV_Movimiento_Ref" IS NOT NULL AND "MAN_Mantenimiento_Ref" IS NULL) '
        'OR ("MOV_Movimiento_Ref" IS NULL AND "MAN_Mantenimiento_Ref" IS NOT NULL)',
    )
    op.alter_column(
        "INV_EVIDENCIA",
        "EVI_URL_Archivo",
        existing_type=sa.String(length=255),
        type_=sa.String(length=500),
    )

    op.create_check_constraint(
        "ck_usuario_rol_valido",
        "INV_USUARIO",
        "\"USU_Rol\" IN ('SUPER_ADMIN', 'ADMIN_TI', 'TECNICO', 'CONSULTA')",
    )
    # USU_Salt es redundante (passlib embebe el salt en el hash).
    op.drop_column("INV_USUARIO", "USU_Salt")

    op.create_check_constraint(
        "ck_persona_email_format",
        "INV_PERSONA",
        "\"PER_Email_Corporativo\" LIKE '%_@_%._%'",
    )

    op.create_unique_constraint(
        "uq_espec_activo_tipo",
        "INV_ESPECIFICACION",
        ["ACT_Activo", "TES_Tipo_Especificacion"],
    )

    op.create_unique_constraint(
        "uq_software_nombre_version_fabr",
        "INV_SOFTWARE",
        ["SOF_Nombre", "SOF_Version", "SOF_Fabricante"],
    )

    op.create_check_constraint(
        "ck_modelo_anio_razonable",
        "INV_MODELO",
        '"MOD_Anio_Lanzamiento" IS NULL OR "MOD_Anio_Lanzamiento" BETWEEN 1970 AND 2100',
    )

    # =========================================================
    # 2. AUDITORÍA: nueva columna + índices
    # =========================================================
    op.add_column(
        "INV_AUDITORIA_SISTEMA",
        sa.Column("AUD_User_Agent", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_auditoria_usuario_fecha",
        "INV_AUDITORIA_SISTEMA",
        ["USU_Usuario", "AUD_Fecha_Hora"],
    )
    op.create_index(
        "ix_auditoria_entidad", "INV_AUDITORIA_SISTEMA", ["AUD_Entidad_Afectada"]
    )

    # =========================================================
    # 3. ÍNDICE PARCIAL UNIQUE: solo un movimiento abierto por activo
    # =========================================================
    op.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_movimiento_activo_abierto '
        'ON "INV_MOVIMIENTO" ("ACT_Activo") '
        'WHERE "MOV_Fecha_Devolucion" IS NULL'
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS uq_movimiento_activo_abierto')
    op.drop_index("ix_auditoria_entidad", table_name="INV_AUDITORIA_SISTEMA")
    op.drop_index("ix_auditoria_usuario_fecha", table_name="INV_AUDITORIA_SISTEMA")
    op.drop_column("INV_AUDITORIA_SISTEMA", "AUD_User_Agent")

    op.drop_constraint("ck_modelo_anio_razonable", "INV_MODELO", type_="check")
    op.drop_constraint("uq_software_nombre_version_fabr", "INV_SOFTWARE", type_="unique")
    op.drop_constraint("uq_espec_activo_tipo", "INV_ESPECIFICACION", type_="unique")
    op.drop_constraint("ck_persona_email_format", "INV_PERSONA", type_="check")
    op.add_column(
        "INV_USUARIO", sa.Column("USU_Salt", sa.String(length=255), nullable=True)
    )
    op.drop_constraint("ck_usuario_rol_valido", "INV_USUARIO", type_="check")
    op.alter_column(
        "INV_EVIDENCIA",
        "EVI_URL_Archivo",
        existing_type=sa.String(length=500),
        type_=sa.String(length=255),
    )
    op.drop_constraint(
        "ck_evidencia_xor_movimiento_mantenimiento", "INV_EVIDENCIA", type_="check"
    )
    op.alter_column(
        "INV_DETALLE_MANT",
        "DMA_Costo_Item",
        existing_type=sa.Numeric(12, 2),
        type_=sa.Numeric(10, 2),
    )
    op.drop_constraint("ck_detalle_costo_no_negativo", "INV_DETALLE_MANT", type_="check")
    op.alter_column(
        "INV_MANTENIMIENTO",
        "MAN_Costo_Total",
        existing_type=sa.Numeric(12, 2),
        type_=sa.Numeric(10, 2),
    )
    op.drop_constraint(
        "ck_mantenimiento_costo_no_negativo", "INV_MANTENIMIENTO", type_="check"
    )
    op.drop_constraint(
        "ck_mantenimiento_cierre_posterior", "INV_MANTENIMIENTO", type_="check"
    )
    op.drop_constraint(
        "ck_movimiento_devolucion_posterior", "INV_MOVIMIENTO", type_="check"
    )
    op.alter_column(
        "INV_LICENCIA",
        "LIC_Clave_Activacion",
        existing_type=sa.String(length=500),
        type_=sa.String(length=255),
    )
    op.drop_constraint("ck_licencia_usada_valida", "INV_LICENCIA", type_="check")
    op.drop_constraint("ck_licencia_total_positivo", "INV_LICENCIA", type_="check")
    op.drop_constraint("uq_activo_serie_fabricante", "INV_ACTIVO", type_="unique")
    op.drop_constraint("ck_activo_costo_no_negativo", "INV_ACTIVO", type_="check")
    op.drop_constraint("ck_activo_padre_distinto_self", "INV_ACTIVO", type_="check")
    op.drop_constraint("ck_activo_garantia_posterior_compra", "INV_ACTIVO", type_="check")
