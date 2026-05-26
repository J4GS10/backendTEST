"""
Bootstrap idempotente de producción.

Crea (si no existen):
- Configuración base.
- Departamento + Cargo "SysAdmin".
- Persona admin.
- Usuario `sa` con contraseña tomada de SUPER_ADMIN_PASSWORD (env).

Idempotencia: si el usuario `sa` ya existe, no hace nada.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets

from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.session import SessionLocal
from app.models.governance import ConfiguracionSistema
from app.models.organization import Cargo, Departamento, Persona, Usuario


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


async def init_production() -> None:
    sa_username = os.getenv("SUPER_ADMIN_USERNAME", "sa")
    sa_email = os.getenv("SUPER_ADMIN_EMAIL", "admin@example.com")
    sa_password = os.getenv("SUPER_ADMIN_PASSWORD")

    if not sa_password:
        sa_password = secrets.token_urlsafe(16)
        log.warning(
            "SUPER_ADMIN_PASSWORD no definida; se generó una temporal: %s "
            "(cámbiala desde la app inmediatamente)",
            sa_password,
        )

    async with SessionLocal() as db:
        existing = await db.execute(select(Usuario).where(Usuario.USU_Username == sa_username))
        if existing.scalar_one_or_none():
            log.info("Usuario %s ya existe; bootstrap omitido.", sa_username)
            return

        # Configuración (si no existe)
        cfg = (
            await db.execute(
                select(ConfiguracionSistema).where(ConfiguracionSistema.SYS_Configuracion == 1)
            )
        ).scalar_one_or_none()
        if not cfg:
            cfg = ConfiguracionSistema(
                SYS_Configuracion=1,
                SYS_Nombre_Empresa=os.getenv("COMPANY_NAME", "Mi Empresa TI"),
                SYS_Idioma_Defecto="es",
            )
            db.add(cfg)

        depto = Departamento(
            DEP_Nombre="SysAdmin",
            DEP_Codigo_Costos="SYS-000",
            DEP_Descripcion="Cuenta raíz del sistema",
        )
        cargo = Cargo(CAR_Nombre="SysAdmin", CAR_Es_Jefatura=True)
        db.add_all([depto, cargo])
        await db.flush()

        persona = Persona(
            PER_Primer_Nombre="System",
            PER_Primer_Apellido="Administrator",
            PER_Email_Corporativo=sa_email,
            DEP_Departamento=depto.DEP_Departamento,
            CAR_Cargo=cargo.CAR_Cargo,
        )
        db.add(persona)
        await db.flush()

        usuario = Usuario(
            USU_Username=sa_username,
            USU_Password_Hash=get_password_hash(sa_password),
            USU_Rol="SUPER_ADMIN",
            PER_Persona=persona.PER_Persona,
            USU_Estado=True,
        )
        db.add(usuario)

        await db.commit()
        log.info("Bootstrap completado. Usuario %s creado.", sa_username)


if __name__ == "__main__":
    asyncio.run(init_production())
