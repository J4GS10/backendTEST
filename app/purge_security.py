"""
Job de limpieza de tablas de seguridad. Ejecutar por cron.

    docker compose exec backend python -m app.purge_security

Elimina:
- Tokens revocados ya expirados.
- Idempotency keys de más de 24h.
"""
import asyncio
import logging

from app.db.session import SessionLocal
from app.repositories.governance import GovernanceRepository

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("purge")


async def main() -> None:
    async with SessionLocal() as db:
        repo = GovernanceRepository(db)
        result = await repo.purge_expired_security_records()
        log.info(
            "Purga completada: %d tokens, %d idempotency keys",
            result["tokens_revocados_eliminados"],
            result["idempotency_keys_eliminadas"],
        )


if __name__ == "__main__":
    asyncio.run(main())
