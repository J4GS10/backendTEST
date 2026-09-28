from contextlib import asynccontextmanager

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import text

from app.core.config import settings
from app.core.read_routing import read_routing_service
from app.db.dialects import dialect_for

log = structlog.get_logger("database")
database_dialect = dialect_for("sqlite" if settings.IS_SQLITE else settings.DB_ENGINE)


def _engine_kwargs(*, read: bool = False) -> dict:
    """Configuración del engine adaptada al motor de BD."""
    if settings.IS_SQLITE:
        # SQLite no soporta pool de conexiones reales en async.
        return {"echo": settings.DB_ECHO, "future": True, "poolclass": NullPool}

    kwargs = {
        "echo": settings.DB_ECHO,
        "future": True,
        "pool_size": settings.DB_READ_POOL_SIZE if read else settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_READ_MAX_OVERFLOW if read else settings.DB_MAX_OVERFLOW,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "pool_pre_ping": True,
    }
    connect_args = database_dialect.connect_args(settings.DB_CONNECT_TIMEOUT_SECONDS)
    if connect_args:
        kwargs["connect_args"] = connect_args
    return kwargs


engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, **_engine_kwargs())
read_engine = (
    create_async_engine(
        settings.SQLALCHEMY_READ_DATABASE_URI,
        **_engine_kwargs(read=True),
    )
    if settings.HAS_READ_REPLICA
    else engine
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

ReadSessionLocal = async_sessionmaker(
    bind=read_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def _set_read_only(session: AsyncSession) -> None:
    if database_dialect.read_only_statement:
        await session.execute(text(database_dialect.read_only_statement))


async def _prepare_replica_session() -> AsyncSession | None:
    session = ReadSessionLocal()
    try:
        await _set_read_only(session)
        replica_status = await read_routing_service.inspect(session)
    except SQLAlchemyError as exc:
        read_routing_service.mark_unavailable(type(exc).__name__)
        read_routing_service.record_fallback("replica_connection_failed")
        log.warning("read_replica.connection_failed", error=str(exc))
        await session.rollback()
        await session.close()
        return None

    if replica_status.suitable_for_reporting:
        read_routing_service.record_replica_read()
        return session

    read_routing_service.record_fallback(
        replica_status.reason or replica_status.status
    )
    await session.rollback()
    await session.close()
    return None


async def get_db():
    """
    Dependencia FastAPI para obtener sesión.

    Patrón: la sesión NO commitea automáticamente al cerrar.
    Cada servicio es responsable de hacer commit. Aquí solo
    garantizamos rollback en caso de excepción y cierre limpio.
    """
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_read_db():
    """
    Dependencia para reporterÃ­a/exports.

    Usa la rÃ©plica si estÃ¡ configurada; si no, cae al primario. En Postgres se
    fuerza READ ONLY para que una ruta de reporte no pueda escribir por error.
    """
    async with reporting_session() as session:
        yield session


@asynccontextmanager
async def reporting_session():
    """
    READ_REPORTING: usa réplica apta; ante caída o lag crítico usa el writer.

    La comprobación se hace dentro de la misma transacción que consumirá el
    endpoint para reducir la ventana de carrera entre health-check y consulta.
    """
    if settings.HAS_READ_REPLICA:
        replica_session = await _prepare_replica_session()
    else:
        replica_session = None

    if replica_session is not None:
        try:
            yield replica_session
        except SQLAlchemyError as exc:
            # La consulta actual no puede repetirse de forma segura aquí; se
            # registra el fallo y la siguiente petición hará preflight/fallback.
            read_routing_service.record_fallback("replica_query_failed")
            log.warning("read_replica.query_failed", error=str(exc))
            raise
        finally:
            await replica_session.rollback()
            await replica_session.close()
        return

    async with SessionLocal() as writer_session:
        try:
            await _set_read_only(writer_session)
            yield writer_session
        except Exception:
            await writer_session.rollback()
            raise
        finally:
            await writer_session.rollback()
