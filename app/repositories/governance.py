"""
Repositorio de Gobernanza: configuración, secuencias atómicas, auditoría.

Sin commits internos: el servicio decide la atomicidad.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from datetime import datetime, timedelta

from app.core.config import settings
from app.core.errors import utcnow_naive
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
        # Asegurar existencia de la secuencia de forma RACE-SAFE: un INSERT con
        # ON CONFLICT DO NOTHING evita que dos altas concurrentes del primer
        # código de un contexto choquen (antes: ambas veían None e insertaban,
        # una fallaba con IntegrityError).
        if settings.IS_SQLITE:
            from sqlalchemy.dialects.sqlite import insert as _insert
        else:
            from sqlalchemy.dialects.postgresql import insert as _insert
        await self.db.execute(
            _insert(Secuencia)
            .values(SEC_Contexto=contexto, SEC_Ultimo_Numero=0, SEC_Relleno=relleno)
            .on_conflict_do_nothing(index_elements=[Secuencia.SEC_Contexto])
        )
        await self.db.flush()

        # Lock de fila (Postgres) + incremento atómico. En SQLite la propia
        # transacción de escritura serializa el acceso.
        query = select(Secuencia).where(Secuencia.SEC_Contexto == contexto)
        if not settings.IS_SQLITE:
            query = query.with_for_update()
        secuencia = (await self.db.execute(query)).scalar_one()

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
        from app.models.governance import (
            IdempotencyKey, PasswordResetToken, TokenRevocado, TwoFactorCode,
        )

        now = utcnow_naive()
        cutoff_idem = now - timedelta(hours=24)

        tok = await self.db.execute(
            delete(TokenRevocado).where(TokenRevocado.TRV_Expira < now)
        )
        idem = await self.db.execute(
            delete(IdempotencyKey).where(IdempotencyKey.IDK_Creada_En < cutoff_idem)
        )
        # Tokens de reset ya expirados o usados (no aportan tras consumirse).
        prt = await self.db.execute(
            delete(PasswordResetToken).where(
                (PasswordResetToken.PRT_Expira < now) | (PasswordResetToken.PRT_Usado.is_(True))
            )
        )
        # Códigos OTP de email 2FA expirados o usados.
        otp = await self.db.execute(
            delete(TwoFactorCode).where(
                (TwoFactorCode.TFC_Expira < now) | (TwoFactorCode.TFC_Usado.is_(True))
            )
        )
        await self.db.commit()
        return {
            "tokens_revocados_eliminados": tok.rowcount,
            "idempotency_keys_eliminadas": idem.rowcount,
            "reset_tokens_eliminados": prt.rowcount,
            "otp_2fa_eliminados": otp.rowcount,
        }

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
        now = utcnow_naive()
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

    # =====================================================================
    # PASSWORD RESET TOKENS
    # =====================================================================
    async def create_reset_token(self, usuario_id: uuid.UUID, token_hash: str, expira: datetime):
        from app.models.governance import PasswordResetToken
        obj = PasswordResetToken(
            USU_Usuario=usuario_id, PRT_Token_Hash=token_hash, PRT_Expira=expira,
        )
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def has_recent_reset_request(self, usuario_id: uuid.UUID, within_minutes: int) -> bool:
        """True si el usuario solicitó un reset dentro de la ventana (throttle por cuenta)."""
        from app.models.governance import PasswordResetToken
        cutoff = utcnow_naive() - timedelta(minutes=within_minutes)
        result = await self.db.execute(
            select(PasswordResetToken.PRT_Id).where(
                PasswordResetToken.USU_Usuario == usuario_id,
                PasswordResetToken.PRT_Creado_En >= cutoff,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def invalidate_user_reset_tokens(self, usuario_id: uuid.UUID) -> None:
        """Marca como usados los tokens de reset pendientes del usuario (1 activo a la vez)."""
        from app.models.governance import PasswordResetToken
        await self.db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.USU_Usuario == usuario_id,
                   PasswordResetToken.PRT_Usado.is_(False))
            .values(PRT_Usado=True)
        )
        await self.db.flush()

    async def get_valid_reset_token(self, token_hash: str):
        """Devuelve el token si existe, no está usado y no ha expirado; si no, None."""
        from app.models.governance import PasswordResetToken
        now = utcnow_naive()
        result = await self.db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.PRT_Token_Hash == token_hash,
                PasswordResetToken.PRT_Usado.is_(False),
                PasswordResetToken.PRT_Expira > now,
            )
        )
        return result.scalar_one_or_none()

    async def mark_reset_token_used(self, prt_id: uuid.UUID) -> None:
        from app.models.governance import PasswordResetToken
        await self.db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.PRT_Id == prt_id)
            .values(PRT_Usado=True)
        )
        await self.db.flush()

    # =====================================================================
    # 2FA — códigos OTP de email + códigos de recuperación
    # =====================================================================
    async def invalidate_email_otps(self, usuario_id: uuid.UUID) -> None:
        from app.models.governance import TwoFactorCode
        await self.db.execute(
            update(TwoFactorCode)
            .where(TwoFactorCode.USU_Usuario == usuario_id, TwoFactorCode.TFC_Usado.is_(False))
            .values(TFC_Usado=True)
        )
        await self.db.flush()

    async def create_email_otp(self, usuario_id: uuid.UUID, code_hash: str, expira: datetime):
        from app.models.governance import TwoFactorCode
        obj = TwoFactorCode(USU_Usuario=usuario_id, TFC_Code_Hash=code_hash, TFC_Expira=expira)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_active_email_otp(self, usuario_id: uuid.UUID):
        from app.models.governance import TwoFactorCode
        now = utcnow_naive()
        result = await self.db.execute(
            select(TwoFactorCode)
            .where(TwoFactorCode.USU_Usuario == usuario_id,
                   TwoFactorCode.TFC_Usado.is_(False),
                   TwoFactorCode.TFC_Expira > now)
            .order_by(TwoFactorCode.TFC_Creado_En.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def bump_email_otp_attempts(self, tfc_id: uuid.UUID) -> None:
        from app.models.governance import TwoFactorCode
        await self.db.execute(
            update(TwoFactorCode).where(TwoFactorCode.TFC_Id == tfc_id)
            .values(TFC_Intentos=TwoFactorCode.TFC_Intentos + 1)
        )
        await self.db.flush()

    async def mark_email_otp_used(self, tfc_id: uuid.UUID) -> None:
        from app.models.governance import TwoFactorCode
        await self.db.execute(
            update(TwoFactorCode).where(TwoFactorCode.TFC_Id == tfc_id).values(TFC_Usado=True)
        )
        await self.db.flush()

    async def delete_recovery_codes(self, usuario_id: uuid.UUID) -> None:
        from sqlalchemy import delete as _delete
        from app.models.governance import RecoveryCode
        await self.db.execute(_delete(RecoveryCode).where(RecoveryCode.USU_Usuario == usuario_id))
        await self.db.flush()

    async def create_recovery_codes(self, usuario_id: uuid.UUID, code_hashes: list[str]) -> None:
        from app.models.governance import RecoveryCode
        for h in code_hashes:
            self.db.add(RecoveryCode(USU_Usuario=usuario_id, TRC_Code_Hash=h))
        await self.db.flush()

    async def consume_recovery_code(self, usuario_id: uuid.UUID, code_hash: str) -> bool:
        """Marca un código de recuperación como usado si existe y no estaba usado."""
        from app.models.governance import RecoveryCode
        result = await self.db.execute(
            update(RecoveryCode)
            .where(RecoveryCode.USU_Usuario == usuario_id,
                   RecoveryCode.TRC_Code_Hash == code_hash,
                   RecoveryCode.TRC_Usado.is_(False))
            .values(TRC_Usado=True)
        )
        await self.db.flush()
        return result.rowcount == 1

    async def count_unused_recovery_codes(self, usuario_id: uuid.UUID) -> int:
        from app.models.governance import RecoveryCode
        result = await self.db.execute(
            select(func.count()).select_from(RecoveryCode)
            .where(RecoveryCode.USU_Usuario == usuario_id, RecoveryCode.TRC_Usado.is_(False))
        )
        return result.scalar_one()

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
