"""
Sesiones de inicio: registro, cierre individual y detección de dispositivos nuevos.

Cada inicio de sesión crea una fila en SYS_SESION; su id viaja en el claim
`sid` de los tokens. Así se puede:
- listar las sesiones activas de una cuenta (autoservicio y administración),
- cerrar UNA sesión sin afectar a las demás (sus tokens dejan de valer),
- avisar al titular cuando se entra desde un dispositivo no visto antes.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from jose import jwt
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get, cache_set
from app.core.config import settings
from app.models.governance import Sesion

log = structlog.get_logger("sessions")

_CLOSED_CACHE = "auth:sid:{sid}"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def device_label(user_agent: str | None) -> str:
    """Huella legible y estable del dispositivo: "Navegador · Sistema"."""
    ua = user_agent or ""
    if re.search(r"Edg/", ua):
        browser = "Edge"
    elif re.search(r"OPR/|Opera", ua):
        browser = "Opera"
    elif re.search(r"Firefox/", ua):
        browser = "Firefox"
    elif re.search(r"Chrome/|CriOS/", ua):
        browser = "Chrome"
    elif re.search(r"Safari/", ua):
        browser = "Safari"
    elif ua:
        browser = "Otro"
    else:
        browser = "Desconocido"
    if re.search(r"Android", ua):
        system = "Android"
    elif re.search(r"iPhone|iPad|iOS", ua):
        system = "iOS"
    elif re.search(r"Windows", ua):
        system = "Windows"
    elif re.search(r"Mac OS X|Macintosh", ua):
        system = "macOS"
    elif re.search(r"Linux", ua):
        system = "Linux"
    else:
        system = "Otro"
    return f"{browser} · {system}"


def token_jti(token: str) -> str | None:
    try:
        return jwt.get_unverified_claims(token).get("jti")
    except Exception:  # noqa: BLE001
        return None


async def open_session(
    db: AsyncSession, *, usuario_id: uuid.UUID, ip: str | None, user_agent: str | None, metodo: str,
) -> tuple[Sesion, bool]:
    """
    Registra una sesión nueva. Devuelve (sesión, es_dispositivo_nuevo). Un
    dispositivo es nuevo si la cuenta ya tenía sesiones y ninguna, en la
    ventana de historial, desde ese navegador y sistema.
    """
    now = _now()
    dispositivo = device_label(user_agent)
    desde = now - timedelta(days=settings.SESSION_HISTORY_DAYS)
    previas = (await db.execute(
        select(func.count()).select_from(Sesion)
        .where(Sesion.USU_Usuario == usuario_id, Sesion.SES_Creada_En >= desde)
    )).scalar_one()
    conocidas = (await db.execute(
        select(func.count()).select_from(Sesion)
        .where(
            Sesion.USU_Usuario == usuario_id,
            Sesion.SES_Creada_En >= desde,
            Sesion.SES_Dispositivo == dispositivo,
        )
    )).scalar_one()
    sesion = Sesion(
        SES_Sesion=uuid.uuid4(),
        USU_Usuario=usuario_id,
        SES_Creada_En=now,
        SES_Ultima_Actividad=now,
        SES_Expira=now + timedelta(hours=settings.SESSION_ABSOLUTE_MAX_HOURS),
        SES_IP=(ip or "")[:45] or None,
        SES_User_Agent=(user_agent or "")[:255] or None,
        SES_Dispositivo=dispositivo,
        SES_Metodo=metodo,
    )
    db.add(sesion)
    await db.flush()
    return sesion, previas > 0 and conocidas == 0


async def get_session(db: AsyncSession, sid: str | uuid.UUID) -> Sesion | None:
    try:
        key = uuid.UUID(str(sid))
    except ValueError:
        return None
    return await db.get(Sesion, key)


def is_active(sesion: Sesion | None) -> bool:
    return sesion is not None and sesion.SES_Cerrada_En is None and sesion.SES_Expira > _now()


async def is_session_closed(db: AsyncSession, sid: str) -> bool:
    """Chequeo por petición (con caché corta; el cierre escribe la marca al instante)."""
    cached = await cache_get(_CLOSED_CACHE.format(sid=sid))
    if cached is not None:
        return bool(cached.get("closed"))
    sesion = await get_session(db, sid)
    closed = sesion is not None and sesion.SES_Cerrada_En is not None
    await cache_set(_CLOSED_CACHE.format(sid=sid), {"closed": closed}, settings.AUTH_CACHE_TTL_SECONDS)
    return closed


async def touch_session(db: AsyncSession, sesion: Sesion, *, refresh_jti: str | None, ip: str | None) -> None:
    sesion.SES_Ultima_Actividad = _now()
    sesion.SES_Refresh_Jti = refresh_jti
    if ip:
        sesion.SES_IP = ip[:45]
    await db.flush()


async def close_session(db: AsyncSession, sesion: Sesion, motivo: str) -> bool:
    """Cierra una sesión y revoca su refresh vigente. False si ya estaba cerrada."""
    if sesion.SES_Cerrada_En is not None:
        return False
    sesion.SES_Cerrada_En = _now()
    sesion.SES_Motivo_Cierre = motivo
    if sesion.SES_Refresh_Jti:
        from app.repositories.governance import GovernanceRepository
        await GovernanceRepository(db).revoke_jti_once(
            sesion.SES_Refresh_Jti, "refresh",
            _now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS + 1), sesion.USU_Usuario,
        )
    await db.flush()
    await cache_set(
        _CLOSED_CACHE.format(sid=sesion.SES_Sesion), {"closed": True}, settings.AUTH_CACHE_TTL_SECONDS,
    )
    return True


async def list_sessions(db: AsyncSession, usuario_id: uuid.UUID | None = None) -> list[Sesion]:
    """Sesiones activas (de una cuenta o de todas), más recientes primero."""
    stmt = (
        select(Sesion)
        .where(Sesion.SES_Cerrada_En.is_(None), Sesion.SES_Expira > _now())
        .order_by(Sesion.SES_Ultima_Actividad.desc())
    )
    if usuario_id is not None:
        stmt = stmt.where(Sesion.USU_Usuario == usuario_id)
    return list((await db.execute(stmt)).scalars().all())


async def expire_stale_sessions(db: AsyncSession) -> int:
    """Marca como cerradas las sesiones cuya vida absoluta terminó."""
    now = _now()
    result = await db.execute(
        update(Sesion)
        .where(Sesion.SES_Cerrada_En.is_(None), Sesion.SES_Expira <= now)
        .values(SES_Cerrada_En=now, SES_Motivo_Cierre="expirada")
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


async def purge_old_sessions(db: AsyncSession) -> int:
    """Borra el historial más antiguo que SESSION_HISTORY_DAYS."""
    limite = _now() - timedelta(days=settings.SESSION_HISTORY_DAYS)
    result = await db.execute(
        delete(Sesion)
        .where(Sesion.SES_Creada_En < limite)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def serialize(sesion: Sesion, *, current_sid: str | None = None) -> dict:
    return {
        "id": str(sesion.SES_Sesion),
        "usuario_id": str(sesion.USU_Usuario),
        "creada_en": sesion.SES_Creada_En.isoformat() if sesion.SES_Creada_En else None,
        "ultima_actividad": sesion.SES_Ultima_Actividad.isoformat() if sesion.SES_Ultima_Actividad else None,
        "expira": sesion.SES_Expira.isoformat() if sesion.SES_Expira else None,
        "ip": sesion.SES_IP,
        "dispositivo": sesion.SES_Dispositivo,
        "metodo": sesion.SES_Metodo,
        "actual": current_sid is not None and str(sesion.SES_Sesion) == str(current_sid),
    }
