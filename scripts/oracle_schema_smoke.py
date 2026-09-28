"""Verify that an Oracle 21c database has the application's baseline objects."""
from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings


EXPECTED_TABLES = {"INV_AUDITORIA_SISTEMA", "SYS_IDEMPOTENCY_KEY", "INV_MOVIMIENTO"}
EXPECTED_INDEXES = {
    "UQ_MOVIMIENTO_ACTIVO_ABIERTO",
    "UQ_MANTENIMIENTO_ACTIVO_ABIERTO",
    "UQ_INSTALACION_ACTIVO_LICENCIA_ACTIVA",
}
EXPECTED_TRIGGER = "TRG_AUDITORIA_APPEND_ONLY"


async def main() -> None:
    if settings.DB_ENGINE != "oracle":
        raise RuntimeError("DB_ENGINE must be oracle for this smoke check")

    engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1 FROM dual"))
            tables = set(
                (await connection.execute(text("SELECT table_name FROM user_tables"))).scalars()
            )
            indexes = set(
                (await connection.execute(text("SELECT index_name FROM user_indexes"))).scalars()
            )
            triggers = set(
                (await connection.execute(text("SELECT trigger_name FROM user_triggers"))).scalars()
            )
    finally:
        await engine.dispose()

    missing_tables = EXPECTED_TABLES - tables
    missing_indexes = EXPECTED_INDEXES - indexes
    if missing_tables or missing_indexes or EXPECTED_TRIGGER not in triggers:
        raise RuntimeError(
            "Oracle baseline is incomplete: "
            f"tables={sorted(missing_tables)}, indexes={sorted(missing_indexes)}, "
            f"trigger_missing={EXPECTED_TRIGGER not in triggers}"
        )
    print("Oracle 21c baseline smoke check passed")


if __name__ == "__main__":
    asyncio.run(main())
