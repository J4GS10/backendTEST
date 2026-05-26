"""
Repositorio de Gobernanza: configuración, secuencias atómicas, auditoría.

Sin commits internos: el servicio decide la atomicidad.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from datetime import datetime, timedelta

from app.core.config import settings
from app.models.governance import AuditoriaSistema, ConfiguracionSistema, Secuencia, TokenRevocado
from app.schemas.governance import ConfigUpdate


class GovernanceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # =====================================================================
    # CONFIGURACIÓN (Singleton)
    # =====================================================================
    async def get_config(self) -> ConfiguracionSistema:
        result = await self.db.execute(
            select(ConfiguracionSistema).where(ConfiguracionSistema.SYS_Configuracion == 1)
        )
        config = result.scalar_one_or_none()

        if not config:
            config = ConfiguracionSistema(SYS_Configuracion=1)
            self.db.add(config)
            await self.db.flush()

        return config

    async def update_config(self, schema: ConfigUpdate) -> ConfiguracionSistema:
        await self.get_config()
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(ConfiguracionSistema)
                .where(ConfiguracionSistema.SYS_Configuracion == 1)
                .values(**data)
            )
            await self.db.flush()
        return await self.get_config()

    # =====================================================================
    # SECUENCIAS — atómicas
    # =====================================================================
    async def get_next_code(
        self, contexto: str, prefijo: str, relleno: int = 5
    ) -> str:
        """
        Genera el siguiente código (Ej: LPT00001) de forma segura.

        - Postgres: usa SELECT ... FOR UPDATE (row lock real).
        - SQLite: el lock de escritura es a nivel base de datos durante
          una transacción, así que la atomicidad se conserva si el llamador
          mantiene la transacción abierta.
        """
        # Asegurar existencia de la secuencia (UPSERT-light).
        existing = await self.db.execute(
            select(Secuencia).where(Secuencia.SEC_Contexto == contexto)
        )
        secuencia = existing.scalar_one_or_none()
        if secuencia is None:
            secuencia = Secuencia(
                SEC_Contexto=contexto, SEC_Ultimo_Numero=0, SEC_Relleno=relleno
            )
            self.db.add(secuencia)
            await self.db.flush()

        # Lock en Postgres
        if not settings.IS_SQLITE:
            locked = await self.db.execute(
                select(Secuencia)
                .where(Secuencia.SEC_Contexto == contexto)
                .with_for_update()
            )
            secuencia = locked.scalar_one()

        secuencia.SEC_Ultimo_Numero += 1
        await self.db.flush()

        numero_str = str(secuencia.SEC_Ultimo_Numero).zfill(secuencia.SEC_Relleno)
        return f"{prefijo}{numero_str}"

    # =====================================================================
    # AUDITORÍA
    # =====================================================================
    # =====================================================================
    # TOKEN REVOCATION (blacklist por jti)
    # =====================================================================
    async def revoke_jti(
        self,
        jti: str,
        tipo: str,
        expira: datetime,
        usuario_id: uuid.UUID | None = None,
    ) -> TokenRevocado:
        obj = TokenRevocado(
            TRV_Jti=jti, TRV_Tipo=tipo, TRV_Expira=expira, USU_Usuario=usuario_id
        )
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def purge_expired_security_records(self) -> dict:
        """
        Limpia registros caducados de las tablas de seguridad para evitar
        crecimiento ilimitado y degradación del hot-path de auth.
        - Tokens revocados cuya expiración ya pasó.
        - Idempotency keys de más de 24h.
        Retorna conteo de filas eliminadas.
        """
        from sqlalchemy import delete
        from app.models.governance import IdempotencyKey, TokenRevocado

        now = datetime.utcnow()
        cutoff_idem = now - timedelta(hours=24)

        tok = await self.db.execute(
            delete(TokenRevocado).where(TokenRevocado.TRV_Expira < now)
        )
        idem = await self.db.execute(
            delete(IdempotencyKey).where(IdempotencyKey.IDK_Creada_En < cutoff_idem)
        )
        await self.db.commit()
        return {"tokens_revocados_eliminados": tok.rowcount, "idempotency_keys_eliminadas": idem.rowcount}

    async def is_jti_revoked(self, jti: str) -> bool:
        result = await self.db.execute(
            select(TokenRevocado).where(TokenRevocado.TRV_Jti == jti)
        )
        return result.scalar_one_or_none() is not None

    async def revoke_all_user_tokens(self, usuario_id: uuid.UUID, expira: datetime):
        """
        Revoca TODOS los tokens emitidos a un usuario hasta este instante
        (cambio de contraseña, offboarding, respuesta a incidente).

        El registro comodín 'USR-ALL-{id}' guarda la marca temporal de la
        última revocación. CRÍTICO: debe ACTUALIZARSE en cada llamada — si solo
        se insertara la primera vez, una segunda revocación no invalidaría los
        tokens emitidos entre la primera y la segunda (bug de obsolescencia).
        """
        now = datetime.utcnow()
        wildcard = f"USR-ALL-{usuario_id}"
        existing = await self.db.execute(
            select(TokenRevocado).where(TokenRevocado.TRV_Jti == wildcard)
        )
        rec = existing.scalar_one_or_none()
        if rec is None:
            self.db.add(TokenRevocado(
                TRV_Jti=wildcard, TRV_Tipo="user_all",
                TRV_Fecha_Revocacion=now, TRV_Expira=expira, USU_Usuario=usuario_id,
            ))
        else:
            # Avanzar la frontera temporal de revocación.
            rec.TRV_Fecha_Revocacion = now
            rec.TRV_Expira = expira
        await self.db.flush()

    async def is_user_globally_revoked(
        self, usuario_id: uuid.UUID, issued_at: datetime
    ) -> bool:
        """Si el usuario fue invalidado globalmente DESPUÉS de la emisión del token."""
        wildcard = f"USR-ALL-{usuario_id}"
        result = await self.db.execute(
            select(TokenRevocado).where(TokenRevocado.TRV_Jti == wildcard)
        )
        rec = result.scalar_one_or_none()
        if rec is None:
            return False
        return rec.TRV_Fecha_Revocacion >= issued_at

    async def create_audit_log(
        self,
        accion: str,
        entidad: str,
        snapshot: dict[str, Any] | None = None,
        usuario_id: uuid.UUID | None = None,
        ip_origen: str | None = None,
        user_agent: str | None = None,
    ) -> AuditoriaSistema:
        log = AuditoriaSistema(
            AUD_Accion=accion,
            AUD_Entidad_Afectada=entidad,
            AUD_Snapshot_JSON=_make_json_safe(snapshot) if snapshot else None,
            USU_Usuario=usuario_id,
            AUD_IP_Origen=ip_origen,
            AUD_User_Agent=user_agent,
        )
        self.db.add(log)
        await self.db.flush()
        return log


def _make_json_safe(obj):
    """Convierte recursivamente Decimal, UUID, datetime, date a tipos JSON-safe."""
    from decimal import Decimal
    from datetime import date, datetime as _dt

    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (uuid.UUID,)):
        return str(obj)
    if isinstance(obj, (_dt, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_safe(v) for v in obj]
    return obj
