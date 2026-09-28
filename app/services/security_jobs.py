"""
Mantenimiento periódico de seguridad (tarea del sistema, sin alcance por sede):

- Sesiones: marca como cerradas las que agotaron su vida absoluta y borra el
  historial más antiguo que SESSION_HISTORY_DAYS.
- Cuentas inactivas: desactiva las que no inician sesión en
  ACCOUNT_INACTIVITY_DISABLE_DAYS días (nunca el último SUPER_ADMIN activo),
  cierra sus sesiones, lo audita y avisa al titular.
- Retención de la bitácora: con AUDIT_RETENTION_DAYS > 0 borra los eventos más
  antiguos (mínimo 365 días) y deja constancia de la purga en la propia bitácora.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

log = structlog.get_logger("security_jobs")

AUDIT_RETENTION_MIN_DAYS = 365


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def disable_inactive_accounts(db: AsyncSession) -> list[str]:
    from app.models.organization import Usuario
    from app.repositories.governance import GovernanceRepository

    days = settings.ACCOUNT_INACTIVITY_DISABLE_DAYS
    if days <= 0:
        return []
    limite = _now() - timedelta(days=days)
    ultima_actividad = func.coalesce(Usuario.USU_Ultimo_Login, Usuario.USU_Creado_En)
    candidatos = (await db.execute(
        select(Usuario).where(Usuario.USU_Estado.is_(True), ultima_actividad < limite)
    )).scalars().all()
    if not candidatos:
        return []

    super_admins_activos = (await db.execute(
        select(func.count()).select_from(Usuario)
        .where(Usuario.USU_Rol == "SUPER_ADMIN", Usuario.USU_Estado.is_(True))
    )).scalar_one()
    gov = GovernanceRepository(db)
    desactivados: list[Usuario] = []
    for user in candidatos:
        if user.USU_Rol == "SUPER_ADMIN":
            if super_admins_activos <= 1:
                log.warning("inactive_accounts.skip_last_super_admin", username=user.USU_Username)
                continue
            super_admins_activos -= 1
        user.USU_Estado = False
        await gov.revoke_all_user_tokens(user.USU_Usuario, expira=_now() + timedelta(days=400))
        await gov.create_audit_log(
            accion="ACCOUNT_AUTO_DISABLED", entidad="INV_USUARIO",
            snapshot={"target_id": str(user.USU_Usuario), "target_username": user.USU_Username,
                      "rol": user.USU_Rol, "dias_inactividad": days,
                      "ultimo_login": user.USU_Ultimo_Login},
        )
        desactivados.append(user)
    await db.commit()

    for user in desactivados:
        try:
            from app.core.email import notify_security_event
            from app.repositories.organization import UsuarioRepository
            full = await UsuarioRepository(db).get_by_id(user.USU_Usuario)
            per = full.persona if full else None
            await notify_security_event(
                "cuenta_desactivada_inactividad",
                persona_nombre=f"{per.PER_Primer_Nombre} {per.PER_Primer_Apellido}" if per else user.USU_Username,
                username=user.USU_Username,
                to_email=per.PER_Email_Corporativo if per else None,
                dias=days,
            )
        except Exception:  # noqa: BLE001 — el aviso es best-effort
            pass
    return [u.USU_Username for u in desactivados]


async def apply_audit_retention(db: AsyncSession) -> int:
    from app.models.governance import AuditoriaSistema
    from app.repositories.governance import GovernanceRepository

    configured = settings.AUDIT_RETENTION_DAYS
    if configured <= 0:
        return 0
    days = max(configured, AUDIT_RETENTION_MIN_DAYS)
    corte = _now() - timedelta(days=days)
    if db.get_bind().dialect.name == "postgresql":
        # Autoriza el borrado ante el trigger append-only solo en esta transacción.
        await db.execute(text("SELECT set_config('app.purga_auditoria', 'on', true)"))
    result = await db.execute(
        delete(AuditoriaSistema).where(AuditoriaSistema.AUD_Fecha_Hora < corte)
        .execution_options(synchronize_session=False)
    )
    borrados = result.rowcount or 0
    if borrados:
        await GovernanceRepository(db).create_audit_log(
            accion="AUDIT_RETENTION_PURGE", entidad="INV_AUDITORIA_SISTEMA",
            snapshot={"registros_eliminados": borrados, "anteriores_a": corte, "retencion_dias": days},
        )
    await db.commit()
    return borrados


async def security_housekeeping(db: AsyncSession) -> dict:
    from app.services import sessions

    expiradas = await sessions.expire_stale_sessions(db)
    purgadas = await sessions.purge_old_sessions(db)
    await db.commit()
    desactivadas = await disable_inactive_accounts(db)
    auditoria = await apply_audit_retention(db)
    return {
        "sesiones_expiradas": expiradas,
        "sesiones_purgadas": purgadas,
        "cuentas_desactivadas": len(desactivadas),
        "auditoria_purgada": auditoria,
    }
