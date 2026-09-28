"""
Configuración EFECTIVA de correo y Active Directory.

Fuentes, en orden de prioridad:
  1. SYS_INTEGRACION_CORREO (fila única, editada desde la UI por SUPER_ADMIN).
  2. Variables de entorno SMTP_* / AD_* (compatibilidad con despliegues previos).

La cuenta de servicio genérica (p. ej. inventario@empresa.com + clave) se usa
para enviar correo (SMTP AUTH o como buzón remitente en Microsoft Graph) y,
en modo CORREO_AD, también para el bind LDAP contra el AD.

Caché: la fila se cachea CACHE_SECONDS por proceso; al guardar desde la API el
proceso que atiende la petición actualiza su caché al instante (write-through)
y los demás workers la ven en ≤ CACHE_SECONDS.

Cortacircuitos (circuit breaker): tras un fallo de AUTENTICACIÓN (clave
incorrecta/expirada) se pausan los intentos BREAKER_MINUTES. Sin esto, los
reintentos de la cola de correos y las consultas de grupos repetirían la clave
mala hasta bloquear la cuenta de servicio en el AD (política de bloqueo), lo
que tumbaría correo y AD a la vez. El estado se comparte vía Redis entre
workers (y en memoria si no hay Redis).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_field, encrypt_field

log = structlog.get_logger("integration_config")

CACHE_SECONDS = 30
BREAKER_MINUTES = 15

MODOS = ("DESACTIVADO", "CORREO", "CORREO_AD")
PROVEEDORES = ("SMTP", "GRAPH")
SEGURIDADES = ("STARTTLS", "SSL", "NINGUNA")


@dataclass(frozen=True)
class MailConfig:
    enabled: bool
    provider: str = "SMTP"                # SMTP | GRAPH
    host: str | None = None
    port: int = 587
    security: str = "STARTTLS"            # STARTTLS | SSL | NINGUNA
    username: str | None = None
    password: str | None = None
    from_email: str | None = None
    from_name: str = "Sistema Inventario"
    graph_tenant_id: str | None = None
    graph_client_id: str | None = None
    graph_client_secret: str | None = None
    timeout: float = 10.0

    @property
    def ready(self) -> bool:
        if not self.enabled:
            return False
        if self.provider == "GRAPH":
            return bool(self.graph_tenant_id and self.graph_client_id and self.graph_client_secret and self.from_email)
        return bool(self.host)


@dataclass(frozen=True)
class AdConfig:
    enabled: bool
    servers: tuple[str, ...] = ()
    base_dn: str = ""
    group_base_dn: str = ""
    user_filter: str = "(&(objectCategory=person)(objectClass=user)(mail=*))"
    admin_group: str = ""
    start_tls: bool = False
    verify_cert: bool = True
    ca_cert_file: str | None = None
    bind_user: str | None = None
    bind_password: str | None = None
    timeout: int = 10
    group_cache_seconds: int = 600
    sync_interval_min: int = 0
    deactivate: bool = True
    default_department: str = "Sin departamento"
    default_cargo: str = "Sin cargo"

    @property
    def configured(self) -> bool:
        return bool(self.servers and self.base_dn and self.bind_user)

    @property
    def ready(self) -> bool:
        return self.enabled and self.configured

    def fingerprint(self) -> tuple:
        return (self.servers, self.base_dn, self.group_base_dn, self.bind_user, self.bind_password,
                self.start_tls, self.verify_cert, self.ca_cert_file, self.user_filter)


@dataclass(frozen=True)
class IntegrationConfig:
    source: str                            # 'interfaz' | 'entorno'
    mode: str
    mail: MailConfig
    ad: AdConfig
    row: dict[str, Any] = field(default_factory=dict, compare=False)


# =========================================================================
# Construcción
# =========================================================================
def _csv_servers(value: str | None) -> tuple[str, ...]:
    return tuple(s.strip() for s in (value or "").split(",") if s.strip())


def _ad_common() -> dict[str, Any]:
    return dict(
        user_filter=settings.AD_USER_FILTER,
        ca_cert_file=settings.AD_CA_CERT_FILE or None,
        timeout=settings.AD_TIMEOUT_SECONDS,
        group_cache_seconds=settings.AD_GROUP_CACHE_SECONDS,
        default_department=settings.AD_DEFAULT_DEPARTMENT,
        default_cargo=settings.AD_DEFAULT_CARGO,
    )


def from_env() -> IntegrationConfig:
    security = "SSL" if settings.SMTP_TLS and settings.SMTP_PORT == 465 else (
        "STARTTLS" if settings.SMTP_STARTTLS else "NINGUNA")
    mail = MailConfig(
        enabled=bool(settings.EMAIL_ENABLED and settings.SMTP_HOST),
        provider="SMTP", host=settings.SMTP_HOST, port=settings.SMTP_PORT, security=security,
        username=settings.SMTP_USER or None, password=settings.SMTP_PASSWORD or None,
        from_email=settings.SMTP_FROM_EMAIL, from_name=settings.SMTP_FROM_NAME,
        timeout=settings.SMTP_TIMEOUT_SECONDS,
    )
    ad = AdConfig(
        enabled=settings.AD_ENABLED,
        servers=_csv_servers(settings.AD_SERVER), base_dn=settings.AD_BASE_DN,
        group_base_dn=settings.AD_GROUP_BASE_DN, admin_group=settings.AD_ADMIN_GROUP,
        start_tls=settings.AD_START_TLS, verify_cert=settings.AD_VERIFY_CERT,
        bind_user=settings.AD_BIND_USER, bind_password=settings.AD_BIND_PASSWORD,
        sync_interval_min=settings.AD_SYNC_INTERVAL_MINUTES, deactivate=settings.AD_SYNC_DEACTIVATE,
        **_ad_common(),
    )
    mode = "CORREO_AD" if ad.enabled and mail.enabled else ("CORREO" if mail.enabled else "DESACTIVADO")
    return IntegrationConfig(source="entorno", mode=mode, mail=mail, ad=ad)


def from_values(v: dict[str, Any], source: str = "interfaz") -> IntegrationConfig:
    """Construye la config desde valores planos (fila de BD ya descifrada o formulario)."""
    mode = v.get("modo") or "DESACTIVADO"
    account_login = v.get("cuenta_usuario") or v.get("cuenta_email")
    mail = MailConfig(
        enabled=mode in ("CORREO", "CORREO_AD") and settings.EMAIL_ENABLED,
        provider=v.get("proveedor") or "SMTP",
        host=v.get("smtp_host") or None,
        port=int(v.get("smtp_puerto") or 587),
        security=v.get("smtp_seguridad") or "STARTTLS",
        username=account_login or None,
        password=v.get("cuenta_password") or None,
        from_email=v.get("cuenta_email") or settings.SMTP_FROM_EMAIL,
        from_name=v.get("nombre_remitente") or settings.SMTP_FROM_NAME,
        graph_tenant_id=v.get("graph_tenant_id") or None,
        graph_client_id=v.get("graph_client_id") or None,
        graph_client_secret=v.get("graph_client_secret") or None,
        timeout=settings.SMTP_TIMEOUT_SECONDS,
    )
    use_account = v.get("ad_usar_cuenta_servicio", True)
    ad = AdConfig(
        enabled=mode == "CORREO_AD",
        servers=_csv_servers(v.get("ad_servidor")),
        base_dn=v.get("ad_base_dn") or "",
        group_base_dn=v.get("ad_grupo_base_dn") or "",
        admin_group=v.get("ad_grupo_admin") or "",
        start_tls=bool(v.get("ad_start_tls")),
        verify_cert=v.get("ad_verificar_cert", True),
        bind_user=(account_login if use_account else v.get("ad_bind_usuario")) or None,
        bind_password=(v.get("cuenta_password") if use_account else v.get("ad_bind_password")) or None,
        sync_interval_min=int(v.get("ad_intervalo_min") or 0),
        deactivate=v.get("ad_desactivar", True),
        **_ad_common(),
    )
    return IntegrationConfig(source=source, mode=mode, mail=mail, ad=ad, row=v)


# Mapeo columna ↔ clave del API
_COLUMNS = {
    "modo": "INT_Modo", "proveedor": "INT_Proveedor",
    "cuenta_email": "INT_Cuenta_Email", "cuenta_usuario": "INT_Cuenta_Usuario",
    "nombre_remitente": "INT_Nombre_Remitente",
    "smtp_host": "INT_SMTP_Host", "smtp_puerto": "INT_SMTP_Puerto", "smtp_seguridad": "INT_SMTP_Seguridad",
    "graph_tenant_id": "INT_Graph_Tenant_Id", "graph_client_id": "INT_Graph_Client_Id",
    "ad_servidor": "INT_AD_Servidor", "ad_base_dn": "INT_AD_Base_DN", "ad_grupo_base_dn": "INT_AD_Grupo_Base_DN",
    "ad_grupo_admin": "INT_AD_Grupo_Admin", "ad_start_tls": "INT_AD_Start_TLS",
    "ad_verificar_cert": "INT_AD_Verificar_Cert", "ad_intervalo_min": "INT_AD_Intervalo_Min",
    "ad_desactivar": "INT_AD_Desactivar", "ad_usar_cuenta_servicio": "INT_AD_Usar_Cuenta_Servicio",
    "ad_bind_usuario": "INT_AD_Bind_Usuario",
}
SECRETS = {
    "cuenta_password": "INT_Cuenta_Password_Enc",
    "graph_client_secret": "INT_Graph_Secret_Enc",
    "ad_bind_password": "INT_AD_Bind_Password_Enc",
}


def row_to_values(row) -> dict[str, Any]:
    v = {k: getattr(row, col) for k, col in _COLUMNS.items()}
    for k, col in SECRETS.items():
        raw = getattr(row, col)
        try:
            v[k] = decrypt_field(raw) if raw else None
        except Exception:  # noqa: BLE001 — clave de cifrado rotada/perdida
            log.error("integration.secret_undecryptable", campo=k)
            v[k] = None
    return v


def apply_values(row, data: dict[str, Any]) -> None:
    """Escribe en la fila. Secretos: None = conservar, "" = borrar, valor = cifrar."""
    for k, col in _COLUMNS.items():
        if k in data:
            setattr(row, col, data[k])
    for k, col in SECRETS.items():
        if data.get(k) is None:
            continue
        setattr(row, col, encrypt_field(data[k]) if data[k] else None)


def merge_with_stored(form: dict[str, Any], stored: dict[str, Any] | None) -> dict[str, Any]:
    """Valores de formulario sin guardar + secretos almacenados si el form no los trae."""
    v = dict(form)
    for k in SECRETS:
        if v.get(k) is None:
            v[k] = (stored or {}).get(k)
    return v


# =========================================================================
# Carga con caché
# =========================================================================
_cache: tuple[float, dict[str, Any] | None] | None = None


def _cache_put(values: dict[str, Any] | None) -> None:
    global _cache
    _cache = (time.monotonic() + CACHE_SECONDS, values)


def invalidate() -> None:
    global _cache
    _cache = None


async def _load_values(db: AsyncSession) -> dict[str, Any] | None:
    from app.models.governance import IntegracionCorreo
    row = await db.get(IntegracionCorreo, 1)
    return row_to_values(row) if row is not None else None


async def get_config(db: AsyncSession | None = None) -> IntegrationConfig:
    """
    Config efectiva. Con `db` lee de esa sesión (y refresca la caché); sin ella
    usa la caché o abre una sesión propia. Nunca lanza: ante error de BD usa
    el último valor conocido o las variables de entorno.
    """
    now = time.monotonic()
    values: dict[str, Any] | None
    if db is not None:
        try:
            values = await _load_values(db)
            _cache_put(values)
        except Exception as e:  # noqa: BLE001
            log.warning("integration.load_failed", error=str(e)[:150])
            values = _cache[1] if _cache else None
    elif _cache is not None and _cache[0] > now:
        values = _cache[1]
    else:
        try:
            from app.db import session as db_session
            async with db_session.SessionLocal() as s:
                values = await _load_values(s)
            _cache_put(values)
        except Exception as e:  # noqa: BLE001
            log.warning("integration.load_failed", error=str(e)[:150])
            values = _cache[1] if _cache else None
    return from_values(values) if values is not None else from_env()


def peek_config() -> IntegrationConfig:
    """Versión síncrona sin E/S (métricas/health): caché vigente o entorno."""
    if _cache is not None and _cache[1] is not None:
        return from_values(_cache[1])
    return from_env()


def set_cached_values(values: dict[str, Any] | None) -> None:
    """Write-through tras guardar desde la API."""
    _cache_put(values)


# =========================================================================
# Cortacircuitos de autenticación
# =========================================================================
_breaker_local: dict[str, float] = {}


def _utc_from_epoch(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)


async def trip_breaker(kind: str, reason: str) -> None:
    """kind: 'smtp' | 'ad'. Pausa los intentos BREAKER_MINUTES."""
    from app.core.cache import get_redis
    until = time.time() + BREAKER_MINUTES * 60
    _breaker_local[kind] = until
    log.error("integration.auth_breaker_tripped", kind=kind, minutes=BREAKER_MINUTES, reason=reason[:150])
    r = get_redis()
    if r is not None:
        try:
            await r.set(f"breaker:{kind}", str(until), ex=BREAKER_MINUTES * 60)
        except Exception:  # noqa: BLE001
            pass


async def breaker_until(kind: str) -> datetime | None:
    from app.core.cache import get_redis
    until = _breaker_local.get(kind, 0.0)
    r = get_redis()
    if r is not None:
        try:
            raw = await r.get(f"breaker:{kind}")
            if raw:
                until = max(until, float(raw))
        except Exception:  # noqa: BLE001
            pass
    return _utc_from_epoch(until) if until > time.time() else None


async def reset_breakers(*kinds: str) -> None:
    """Reanuda los intentos (todos, o solo los `kinds` indicados)."""
    from app.core.cache import get_redis
    kinds = kinds or ("smtp", "ad")
    for k in kinds:
        _breaker_local.pop(k, None)
    r = get_redis()
    if r is not None:
        try:
            await r.delete(*(f"breaker:{k}" for k in kinds))
        except Exception:  # noqa: BLE001
            pass
