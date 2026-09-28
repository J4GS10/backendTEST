"""
Instala (o reinstala) la capa RLS de PostgreSQL: rol restringido, permisos,
funciones y políticas. Idempotente.

Uso (con credenciales de un usuario que pueda crear roles, p. ej. el dueño
de la base en la instalación Docker):

    python -m app.db.install_rls
"""
from __future__ import annotations

import asyncio

from app.core.config import settings
from app.db.rls import check_rls, install_rls
from app.db.session import engine


async def main() -> int:
    if engine.dialect.name != "postgresql":
        print("RLS por sede en base de datos solo aplica a PostgreSQL.")
        return 1
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: install_rls(c, strict=True))
    async with engine.connect() as conn:
        ok, reason = await conn.run_sync(check_rls)
    print(f"RLS instalado para el rol {settings.DB_RLS_ROLE}: {'OK' if ok else reason}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
