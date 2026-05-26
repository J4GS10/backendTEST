"""fks_ondelete

Recrea las foreign keys con ON DELETE explícito para preservar
integridad referencial al borrar catálogos o entidades.

Reglas:
- RESTRICT  -> evita borrar catálogos/entidades referenciadas.
- CASCADE   -> detalles débiles que pertenecen al padre.
- SET NULL  -> bitácora (auditoría) sigue existiendo si borran al usuario.

Revision ID: f2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2025-12-09 00:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (tabla, column, ref_table, ref_column, ondelete)
FKS = [
    ("INV_ACTIVO", "MOD_Modelo", "INV_MODELO", "MOD_Modelo", "RESTRICT"),
    ("INV_ACTIVO", "TAC_Tipo_Activo", "INV_TIPO_ACTIVO", "TAC_Tipo_Activo", "RESTRICT"),
    ("INV_ACTIVO", "EOP_Estado_Operativo", "INV_ESTADO_OPERATIVO", "EOP_Estado_Operativo", "RESTRICT"),
    ("INV_ACTIVO", "ACT_Activo_Padre", "INV_ACTIVO", "ACT_Activo", "SET NULL"),
    ("INV_AREA", "NIV_Nivel", "INV_NIVEL", "NIV_Nivel", "RESTRICT"),
    ("INV_AUDITORIA_SISTEMA", "USU_Usuario", "INV_USUARIO", "USU_Usuario", "SET NULL"),
    ("INV_DETALLE_MANT", "MAN_Mantenimiento", "INV_MANTENIMIENTO", "MAN_Mantenimiento", "CASCADE"),
    ("INV_EDIFICIO", "SED_Sede", "INV_SEDE", "SED_Sede", "RESTRICT"),
    ("INV_ESPECIFICACION", "ACT_Activo", "INV_ACTIVO", "ACT_Activo", "CASCADE"),
    ("INV_ESPECIFICACION", "TES_Tipo_Especificacion", "INV_TIPO_ESPECIFICACION", "TES_Tipo_Especificacion", "RESTRICT"),
    ("INV_ESTADO", "PAI_Pais", "INV_PAIS", "PAI_Pais", "RESTRICT"),
    ("INV_EVIDENCIA", "MOV_Movimiento_Ref", "INV_MOVIMIENTO", "MOV_Movimiento", "CASCADE"),
    ("INV_EVIDENCIA", "MAN_Mantenimiento_Ref", "INV_MANTENIMIENTO", "MAN_Mantenimiento", "CASCADE"),
    ("INV_EVIDENCIA", "TEV_Tipo_Evidencia", "INV_TIPO_EVIDENCIA", "TEV_Tipo_Evidencia", "RESTRICT"),
    ("INV_INSTALACION", "ACT_Activo", "INV_ACTIVO", "ACT_Activo", "CASCADE"),
    ("INV_INSTALACION", "LIC_Licencia", "INV_LICENCIA", "LIC_Licencia", "RESTRICT"),
    ("INV_LICENCIA", "SOF_Software", "INV_SOFTWARE", "SOF_Software", "RESTRICT"),
    ("INV_LICENCIA", "TLI_Tipo_Licencia", "INV_TIPO_LICENCIA", "TLI_Tipo_Licencia", "RESTRICT"),
    ("INV_MANTENIMIENTO", "ACT_Activo", "INV_ACTIVO", "ACT_Activo", "RESTRICT"),
    ("INV_MANTENIMIENTO", "PER_Persona_Solicita", "INV_PERSONA", "PER_Persona", "RESTRICT"),
    ("INV_MANTENIMIENTO", "TMA_Tipo_Mantenimiento", "INV_TIPO_MANTENIMIENTO", "TMA_Tipo_Mantenimiento", "RESTRICT"),
    ("INV_MODELO", "MAR_Marca", "INV_MARCA", "MAR_Marca", "RESTRICT"),
    ("INV_MODELO", "TCN_Tipo_Conexion", "INV_TIPO_CONEXION", "TCN_Tipo_Conexion", "SET NULL"),
    ("INV_MOVIMIENTO", "ACT_Activo", "INV_ACTIVO", "ACT_Activo", "RESTRICT"),
    ("INV_MOVIMIENTO", "PER_Persona", "INV_PERSONA", "PER_Persona", "RESTRICT"),
    ("INV_MOVIMIENTO", "ARE_Area", "INV_AREA", "ARE_Area", "RESTRICT"),
    ("INV_MOVIMIENTO", "TMO_Tipo_Movimiento", "INV_TIPO_MOVIMIENTO", "TMO_Tipo_Movimiento", "RESTRICT"),
    ("INV_MUNICIPIO", "EST_Estado", "INV_ESTADO", "EST_Estado", "RESTRICT"),
    ("INV_NIVEL", "EDI_Edificio", "INV_EDIFICIO", "EDI_Edificio", "RESTRICT"),
    ("INV_PERSONA", "DEP_Departamento", "INV_DEPARTAMENTO", "DEP_Departamento", "RESTRICT"),
    ("INV_PERSONA", "CAR_Cargo", "INV_CARGO", "CAR_Cargo", "RESTRICT"),
    ("INV_SEDE", "MUN_Municipio", "INV_MUNICIPIO", "MUN_Municipio", "RESTRICT"),
    ("INV_USUARIO", "PER_Persona", "INV_PERSONA", "PER_Persona", "RESTRICT"),
]


def _fk_name(table: str, column: str) -> str:
    """Nombre por defecto que usa Alembic/SQLAlchemy: <tabla>_<col>_fkey"""
    return f"{table}_{column}_fkey"


def upgrade() -> None:
    for table, col, ref_table, ref_col, ondelete in FKS:
        fk = _fk_name(table, col)
        op.drop_constraint(fk, table, type_="foreignkey")
        op.create_foreign_key(
            fk,
            table,
            ref_table,
            [col],
            [ref_col],
            ondelete=ondelete,
        )


def downgrade() -> None:
    for table, col, ref_table, ref_col, _ in FKS:
        fk = _fk_name(table, col)
        op.drop_constraint(fk, table, type_="foreignkey")
        op.create_foreign_key(fk, table, ref_table, [col], [ref_col])
