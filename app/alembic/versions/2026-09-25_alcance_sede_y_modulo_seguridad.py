"""Alcance de datos por sede (RLS), rol AUDITOR, sesiones e historial de contraseñas.

- INV_USUARIO: USU_Alcance_Global, USU_Creado_En y rol AUDITOR.
- INV_USUARIO_SEDE: sedes de un usuario sin alcance global.
- SED_Sede en INV_ACTIVO, INV_PERSONA, INV_ORDEN_COMPRA e INV_CONSUMIBLE.
- AUD_Sede en la bitácora (auditor con alcance por sede).
- SYS_SESION y SYS_PASSWORD_HISTORIAL.
- PostgreSQL: rol restringido, funciones y políticas RLS (app/db/rls.py) y
  purga por retención de la bitácora sin romper su trigger append-only.

Sin cortes de acceso: los usuarios existentes de roles de inventario quedan
con alcance global (como hasta ahora) y la sede de cada activo y persona se
deduce de su última asignación. Si solo hay una sede, todo queda en ella.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-09-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLES_NEW = "\"USU_Rol\" IN ('SUPER_ADMIN', 'ADMIN_SEGURIDAD', 'ADMIN_TI', 'TECNICO', 'AUDITOR', 'CONSULTA')"
_ROLES_OLD = "\"USU_Rol\" IN ('SUPER_ADMIN', 'ADMIN_SEGURIDAD', 'ADMIN_TI', 'TECNICO', 'CONSULTA')"
_SEDE_TABLES = {
    "INV_ACTIVO": "activo",
    "INV_PERSONA": "persona",
    "INV_ORDEN_COMPRA": "orden_compra",
    "INV_CONSUMIBLE": "consumible",
}

# Sede de un área: Área → Nivel → Edificio → Sede.
_AREA_SEDE = """
    SELECT e."SED_Sede"
    FROM "INV_MOVIMIENTO" m
    JOIN "INV_AREA" ar ON ar."ARE_Area" = m."ARE_Area"
    JOIN "INV_NIVEL" n ON n."NIV_Nivel" = ar."NIV_Nivel"
    JOIN "INV_EDIFICIO" e ON e."EDI_Edificio" = n."EDI_Edificio"
"""


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # ---- Usuario: alcance, fecha de alta y rol AUDITOR -------------------
    with op.batch_alter_table("INV_USUARIO") as batch:
        batch.add_column(sa.Column(
            "USU_Alcance_Global", sa.Boolean(), nullable=False, server_default=sa.false(),
        ))
        batch.add_column(sa.Column("USU_Creado_En", sa.DateTime(), nullable=True,
                                   server_default=sa.func.now()))
        batch.drop_constraint("ck_usuario_rol_valido", type_="check")
        batch.create_check_constraint("ck_usuario_rol_valido", _ROLES_NEW)

    op.create_table(
        "INV_USUARIO_SEDE",
        sa.Column("USU_Usuario", sa.Uuid(), sa.ForeignKey("INV_USUARIO.USU_Usuario", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("SED_Sede", sa.Integer(), sa.ForeignKey("INV_SEDE.SED_Sede", ondelete="CASCADE"),
                  primary_key=True),
    )
    op.create_index("ix_INV_USUARIO_SEDE_SED_Sede", "INV_USUARIO_SEDE", ["SED_Sede"])

    # ---- Sede propia de los registros con alcance -------------------------
    for table, short in _SEDE_TABLES.items():
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("SED_Sede", sa.Integer(), nullable=True))
            batch.create_foreign_key(f"fk_{short}_sede", "INV_SEDE", ["SED_Sede"], ["SED_Sede"],
                                     ondelete="RESTRICT")
            batch.create_index(f"ix_{table}_SED_Sede", ["SED_Sede"])

    with op.batch_alter_table("INV_AUDITORIA_SISTEMA") as batch:
        batch.add_column(sa.Column("AUD_Sede", sa.Integer(), nullable=True))
        batch.create_index("ix_INV_AUDITORIA_SISTEMA_AUD_Sede", ["AUD_Sede"])

    # ---- Sesiones e historial de contraseñas ------------------------------
    op.create_table(
        "SYS_SESION",
        sa.Column("SES_Sesion", sa.Uuid(), primary_key=True),
        sa.Column("USU_Usuario", sa.Uuid(), sa.ForeignKey("INV_USUARIO.USU_Usuario", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("SES_Creada_En", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("SES_Ultima_Actividad", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("SES_Expira", sa.DateTime(), nullable=False),
        sa.Column("SES_IP", sa.String(length=45), nullable=True),
        sa.Column("SES_User_Agent", sa.String(length=255), nullable=True),
        sa.Column("SES_Dispositivo", sa.String(length=60), nullable=True),
        sa.Column("SES_Metodo", sa.String(length=10), nullable=False, server_default="password"),
        sa.Column("SES_Refresh_Jti", sa.String(length=64), nullable=True),
        sa.Column("SES_Cerrada_En", sa.DateTime(), nullable=True),
        sa.Column("SES_Motivo_Cierre", sa.String(length=30), nullable=True),
    )
    op.create_index("ix_SYS_SESION_USU_Usuario", "SYS_SESION", ["USU_Usuario"])
    op.create_index("ix_sesion_usuario_activa", "SYS_SESION", ["USU_Usuario", "SES_Cerrada_En"])

    op.create_table(
        "SYS_PASSWORD_HISTORIAL",
        sa.Column("PWH_Id", sa.Uuid(), primary_key=True),
        sa.Column("USU_Usuario", sa.Uuid(), sa.ForeignKey("INV_USUARIO.USU_Usuario", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("PWH_Hash", sa.String(length=255), nullable=False),
        sa.Column("PWH_Creado_En", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_SYS_PASSWORD_HISTORIAL_USU_Usuario", "SYS_PASSWORD_HISTORIAL", ["USU_Usuario"])
    op.create_index("ix_SYS_PASSWORD_HISTORIAL_PWH_Creado_En", "SYS_PASSWORD_HISTORIAL", ["PWH_Creado_En"])

    # ---- Backfill ----------------------------------------------------------
    # 1. Sin cortes de acceso: los roles de inventario existentes siguen viendo todo.
    op.execute(
        "UPDATE \"INV_USUARIO\" SET \"USU_Alcance_Global\" = TRUE "
        "WHERE \"USU_Rol\" IN ('ADMIN_TI', 'TECNICO', 'CONSULTA')"
    )
    op.execute("UPDATE \"INV_USUARIO\" SET \"USU_Creado_En\" = CURRENT_TIMESTAMP WHERE \"USU_Creado_En\" IS NULL")

    # 2. Activo: sede del área de su asignación vigente (o la más reciente).
    op.execute(f"""
        UPDATE "INV_ACTIVO" SET "SED_Sede" = (
            {_AREA_SEDE}
            WHERE m."ACT_Activo" = "INV_ACTIVO"."ACT_Activo"
            ORDER BY CASE WHEN m."MOV_Fecha_Devolucion" IS NULL THEN 0 ELSE 1 END,
                     m."MOV_Fecha_Asignacion" DESC
            LIMIT 1
        )
        WHERE "SED_Sede" IS NULL
    """)
    # 3. Persona: sede del área de su asignación más reciente.
    op.execute(f"""
        UPDATE "INV_PERSONA" SET "SED_Sede" = (
            {_AREA_SEDE}
            WHERE m."PER_Persona" = "INV_PERSONA"."PER_Persona"
            ORDER BY CASE WHEN m."MOV_Fecha_Devolucion" IS NULL THEN 0 ELSE 1 END,
                     m."MOV_Fecha_Asignacion" DESC
            LIMIT 1
        )
        WHERE "SED_Sede" IS NULL
    """)
    # 4. Orden de compra: sede de los activos que recibió.
    op.execute("""
        UPDATE "INV_ORDEN_COMPRA" SET "SED_Sede" = (
            SELECT a."SED_Sede"
            FROM "INV_ORDEN_COMPRA_LINEA" l
            JOIN "INV_ORDEN_COMPRA_LINEA_ACTIVO" la ON la."OCL_Linea" = l."OCL_Linea"
            JOIN "INV_ACTIVO" a ON a."ACT_Activo" = la."ACT_Activo"
            WHERE l."OCO_Orden" = "INV_ORDEN_COMPRA"."OCO_Orden" AND a."SED_Sede" IS NOT NULL
            LIMIT 1
        )
        WHERE "SED_Sede" IS NULL
    """)
    # 5. Con una sola sede registrada, todo lo que quede sin sede pertenece a ella.
    sedes = bind.execute(sa.text('SELECT "SED_Sede" FROM "INV_SEDE"')).scalars().all()
    if len(sedes) == 1:
        for table in _SEDE_TABLES:
            op.execute(sa.text(f'UPDATE "{table}" SET "SED_Sede" = :s WHERE "SED_Sede" IS NULL')
                       .bindparams(s=sedes[0]))

    if is_pg:
        # La purga por retención (tarea del sistema, dueño de la tabla) puede
        # borrar marcando la transacción; el rol de las peticiones no tiene
        # permiso DELETE, así que la bitácora sigue siendo inmutable para ellas.
        op.execute("""
            CREATE OR REPLACE FUNCTION inv_auditoria_append_only()
            RETURNS trigger AS $$
            BEGIN
                IF TG_OP = 'DELETE' AND current_setting('app.purga_auditoria', true) = 'on' THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'INV_AUDITORIA_SISTEMA es append-only: % no permitido', TG_OP;
            END;
            $$ LANGUAGE plpgsql;
        """)
        from app.db.rls import install_rls
        if not install_rls(bind):
            print(
                "AVISO: el usuario de la migración no puede crear el rol de RLS. "
                "Cree el rol manualmente (ver DEPLOYMENT.md, 'Alcance por sede') y "
                "vuelva a ejecutar: python -m app.db.install_rls"
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from app.db.rls import uninstall_rls
        uninstall_rls(bind)
        op.execute("""
            CREATE OR REPLACE FUNCTION inv_auditoria_append_only()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'INV_AUDITORIA_SISTEMA es append-only: % no permitido', TG_OP;
            END;
            $$ LANGUAGE plpgsql;
        """)

    op.drop_index("ix_SYS_PASSWORD_HISTORIAL_PWH_Creado_En", table_name="SYS_PASSWORD_HISTORIAL")
    op.drop_index("ix_SYS_PASSWORD_HISTORIAL_USU_Usuario", table_name="SYS_PASSWORD_HISTORIAL")
    op.drop_table("SYS_PASSWORD_HISTORIAL")
    op.drop_index("ix_sesion_usuario_activa", table_name="SYS_SESION")
    op.drop_index("ix_SYS_SESION_USU_Usuario", table_name="SYS_SESION")
    op.drop_table("SYS_SESION")

    with op.batch_alter_table("INV_AUDITORIA_SISTEMA") as batch:
        batch.drop_index("ix_INV_AUDITORIA_SISTEMA_AUD_Sede")
        batch.drop_column("AUD_Sede")
    for table, short in _SEDE_TABLES.items():
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_SED_Sede")
            batch.drop_constraint(f"fk_{short}_sede", type_="foreignkey")
            batch.drop_column("SED_Sede")

    op.drop_index("ix_INV_USUARIO_SEDE_SED_Sede", table_name="INV_USUARIO_SEDE")
    op.drop_table("INV_USUARIO_SEDE")
    op.execute("UPDATE \"INV_USUARIO\" SET \"USU_Rol\" = 'CONSULTA' WHERE \"USU_Rol\" = 'AUDITOR'")
    with op.batch_alter_table("INV_USUARIO") as batch:
        batch.drop_constraint("ck_usuario_rol_valido", type_="check")
        batch.create_check_constraint("ck_usuario_rol_valido", _ROLES_OLD)
        batch.drop_column("USU_Creado_En")
        batch.drop_column("USU_Alcance_Global")
