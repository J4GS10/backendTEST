import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from app.models.governance import AuditoriaSistema, ConfiguracionSistema, Secuencia
from alembic import context

from app.core.config import settings
from app.db.base import Base

# =========================================================
# IMPORTACIÓN DE TODOS LOS MODELOS (CRÍTICO PARA MIGRACIÓN)
# =========================================================
from app.models.organization import Departamento, Cargo, Persona, Usuario
from app.models.location import Pais, Estado, Municipio, Sede, Edificio, Nivel, Area
from app.models.catalogs import TipoActivo, Marca, TipoConexion, Modelo, EstadoOperativo, TipoEspecificacion
from app.models.core import Activo, Especificacion
from app.models.software import TipoLicencia, Software, Licencia, Instalacion
from app.models.traceability import TipoMovimiento, Movimiento, TipoMantenimiento, Mantenimiento, DetalleMantenimiento, TipoEvidencia, Evidencia
from app.models.governance import AuditoriaSistema, ConfiguracionSistema

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    # Inyección directa de URL para seguridad y manejo de caracteres especiales
    url = settings.SQLALCHEMY_DATABASE_URI
    
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    
    # 1. Obtener configuración base
    configuration = config.get_section(config.config_ini_section) or {}
    
    # 2. Sobrescribir URL directamente con la variable de entorno procesada
    configuration["sqlalchemy.url"] = settings.SQLALCHEMY_DATABASE_URI

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())