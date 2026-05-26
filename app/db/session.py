from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings


def _engine_kwargs() -> dict:
    """Configuración del engine adaptada al motor de BD."""
    if settings.IS_SQLITE:
        # SQLite no soporta pool de conexiones reales en async.
        return {"echo": settings.DB_ECHO, "future": True, "poolclass": NullPool}

    return {
        "echo": settings.DB_ECHO,
        "future": True,
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "pool_pre_ping": True,
    }


engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, **_engine_kwargs())

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


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
