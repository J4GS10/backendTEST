"""
Cliente de Active Directory (LDAP) para el directorio de personas y grupos.

Diseño:
- `DirectoryClient` es la abstracción que consumen los servicios
  (sincronización y resolución de destinatarios). Los tests inyectan un fake
  con `set_directory_client()`.
- `LdapDirectoryClient` usa ldap3 (síncrono) dentro de `asyncio.to_thread`
  para no bloquear el event loop.
- Bind SIMPLE con UPN (svc@empresa.local). Se exige canal cifrado (LDAPS o
  StartTLS) en producción: un bind simple por LDAP plano expone la contraseña.
- Membresía de grupos con LDAP_MATCHING_RULE_IN_CHAIN → incluye grupos anidados.
"""
from __future__ import annotations

import asyncio
import ssl
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.core.config import settings
from app.services.integration_config import AdConfig

log = structlog.get_logger("active_directory")

# userAccountControl: bit ACCOUNTDISABLE
_UAC_ACCOUNT_DISABLE = 0x2
# OID de LDAP_MATCHING_RULE_IN_CHAIN (membresía transitiva).
_IN_CHAIN = "1.2.840.113556.1.4.1941"

_USER_ATTRIBUTES = [
    "objectGUID", "distinguishedName", "sAMAccountName", "userPrincipalName",
    "mail", "givenName", "sn", "department", "title", "telephoneNumber",
    "mobile", "manager", "userAccountControl",
]


class DirectoryError(Exception):
    """Fallo de conexión, bind o búsqueda contra el directorio."""


class DirectoryAuthError(DirectoryError):
    """Credenciales de la cuenta de servicio rechazadas (o cuenta bloqueada)."""


@dataclass(frozen=True)
class DirectoryUser:
    guid: str
    dn: str
    email: str | None
    given_name: str | None = None
    surname: str | None = None
    username: str | None = None
    department: str | None = None
    title: str | None = None
    phone: str | None = None
    manager_dn: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class DirectoryGroup:
    nombre: str
    dn: str


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float = field(default=0.0)


class DirectoryClient(ABC):
    @abstractmethod
    async def test_connection(self) -> int:
        """Hace bind y cuenta usuarios del filtro. Lanza DirectoryError."""

    @abstractmethod
    async def list_users(self) -> list[DirectoryUser]:
        """Todos los usuarios bajo AD_BASE_DN que cumplen AD_USER_FILTER (incluye deshabilitados)."""

    @abstractmethod
    async def group_member_emails(self, group: str) -> list[str]:
        """Emails de los miembros (transitivos, habilitados) de un grupo por nombre o DN."""

    @abstractmethod
    async def search_groups(self, query: str, limit: int = 20) -> list[DirectoryGroup]:
        """Grupos cuyo nombre contiene `query` (para autocompletar)."""


# =========================================================================
# Implementación LDAP
# =========================================================================
def _first(entry: Any, attr: str) -> Any:
    raw = entry.get(attr) if isinstance(entry, dict) else None
    if isinstance(raw, list):
        return raw[0] if raw else None
    return raw


def _escape(value: str) -> str:
    """Escape de filtros LDAP (RFC 4515) para valores provistos por usuarios."""
    from ldap3.utils.conv import escape_filter_chars
    return escape_filter_chars(value)


def _guid_to_str(raw: Any) -> str:
    if isinstance(raw, bytes):
        return str(uuid.UUID(bytes_le=raw))
    return str(raw).strip("{}").lower()


def _to_user(attrs: dict[str, Any]) -> DirectoryUser | None:
    guid = _first(attrs, "objectGUID")
    dn = _first(attrs, "distinguishedName")
    if not guid or not dn:
        return None
    uac = _first(attrs, "userAccountControl") or 0
    try:
        enabled = not (int(uac) & _UAC_ACCOUNT_DISABLE)
    except (TypeError, ValueError):
        enabled = True
    mail = _first(attrs, "mail")
    return DirectoryUser(
        guid=_guid_to_str(guid),
        dn=str(dn),
        email=str(mail).strip().lower() if mail else None,
        given_name=_first(attrs, "givenName"),
        surname=_first(attrs, "sn"),
        username=_first(attrs, "sAMAccountName"),
        department=_first(attrs, "department"),
        title=_first(attrs, "title"),
        phone=_first(attrs, "telephoneNumber") or _first(attrs, "mobile"),
        manager_dn=_first(attrs, "manager"),
        enabled=enabled,
    )


class LdapDirectoryClient(DirectoryClient):
    """
    Cliente LDAP sobre una AdConfig concreta. Si `use_breaker` (uso normal),
    un fallo de autenticación dispara el cortacircuitos 'ad' y, mientras esté
    activo, no se intenta ningún bind (protege la cuenta de servicio de un
    bloqueo por la política de intentos fallidos del AD).
    """

    def __init__(self, cfg: AdConfig, use_breaker: bool = True) -> None:
        self.cfg = cfg
        self.use_breaker = use_breaker
        self._cache: dict[str, _CacheEntry] = {}

    # ---- conexión -------------------------------------------------------
    def _connect(self):
        from ldap3 import SIMPLE, Connection, Server, ServerPool, Tls
        from ldap3.core.exceptions import LDAPBindError, LDAPException, LDAPInvalidCredentialsResult

        cfg = self.cfg
        if not cfg.configured:
            raise DirectoryError("AD_NOT_CONFIGURED")
        urls = list(cfg.servers)
        secure = cfg.start_tls or all(u.lower().startswith("ldaps://") for u in urls)
        if not secure and settings.IS_PRODUCTION:
            raise DirectoryError("AD_INSECURE_CHANNEL: usar ldaps:// o StartTLS")

        tls = Tls(
            validate=ssl.CERT_REQUIRED if cfg.verify_cert else ssl.CERT_NONE,
            ca_certs_file=cfg.ca_cert_file or None,
        )
        servers = [
            Server(u, use_ssl=u.lower().startswith("ldaps://"), tls=tls, connect_timeout=cfg.timeout)
            for u in urls
        ]
        target = servers[0] if len(servers) == 1 else ServerPool(servers, active=True, exhaust=True)
        try:
            conn = Connection(
                target, user=cfg.bind_user, password=cfg.bind_password, authentication=SIMPLE,
                receive_timeout=cfg.timeout, auto_bind=False, read_only=True, raise_exceptions=True,
            )
            conn.open()
            if cfg.start_tls:
                conn.start_tls()
            conn.bind()
            return conn
        except (LDAPInvalidCredentialsResult, LDAPBindError) as e:
            raise DirectoryAuthError(f"AD_AUTH_FAILED: {type(e).__name__}") from e
        except LDAPException as e:
            raise DirectoryError(f"AD_CONNECTION_FAILED: {type(e).__name__}") from e

    def _paged(self, base: str, flt: str, attrs: list[str]) -> list[dict[str, Any]]:
        from ldap3 import SUBTREE
        from ldap3.core.exceptions import LDAPException

        conn = self._connect()
        try:
            results = conn.extend.standard.paged_search(
                search_base=base, search_filter=flt, search_scope=SUBTREE,
                attributes=attrs, paged_size=500, generator=False,
            )
            return [r["attributes"] for r in results if r.get("type") == "searchResEntry"]
        except LDAPException as e:
            raise DirectoryError(f"AD_SEARCH_FAILED: {type(e).__name__}") from e
        finally:
            conn.unbind()

    async def _run(self, fn, *args):
        """Ejecuta una operación LDAP en un hilo respetando el cortacircuitos."""
        from app.services.integration_config import breaker_until, trip_breaker
        if self.use_breaker and await breaker_until("ad"):
            raise DirectoryAuthError("AD_AUTH_PAUSED")
        try:
            return await asyncio.to_thread(fn, *args)
        except DirectoryAuthError as e:
            if self.use_breaker:
                await trip_breaker("ad", str(e))
            raise

    # ---- API ------------------------------------------------------------
    async def test_connection(self) -> int:
        users = await self.list_users()
        return len(users)

    async def list_users(self) -> list[DirectoryUser]:
        rows = await self._run(self._paged, self.cfg.base_dn, self.cfg.user_filter, _USER_ATTRIBUTES)
        return [u for u in (_to_user(r) for r in rows) if u]

    def _group_base(self) -> str:
        return self.cfg.group_base_dn or self.cfg.base_dn

    def _resolve_group_dn(self, group: str) -> str | None:
        if "=" in group and "," in group:
            return group
        rows = self._paged(
            self._group_base(),
            f"(&(objectClass=group)(|(cn={_escape(group)})(sAMAccountName={_escape(group)})))",
            ["distinguishedName"],
        )
        return str(_first(rows[0], "distinguishedName")) if rows else None

    def _members_sync(self, group: str) -> list[str]:
        dn = self._resolve_group_dn(group)
        if not dn:
            log.warning("ad.group_not_found", group=group)
            return []
        flt = (
            "(&(objectCategory=person)(objectClass=user)(mail=*)"
            f"(!(userAccountControl:1.2.840.113556.1.4.803:={_UAC_ACCOUNT_DISABLE}))"
            f"(memberOf:{_IN_CHAIN}:={_escape(dn)}))"
        )
        # La búsqueda de miembros usa la raíz del dominio de base_dn para
        # incluir miembros fuera de la OU de usuarios sincronizados.
        root = ",".join(p for p in self.cfg.base_dn.split(",") if p.strip().upper().startswith("DC="))
        rows = self._paged(root or self.cfg.base_dn, flt, ["mail"])
        return sorted({str(_first(r, "mail")).strip().lower() for r in rows if _first(r, "mail")})

    async def group_member_emails(self, group: str) -> list[str]:
        key = f"members:{group.lower()}"
        hit = self._cache.get(key)
        now = time.monotonic()
        if hit and hit.expires_at > now:
            return hit.value
        try:
            emails = await self._run(self._members_sync, group)
        except DirectoryError:
            # Si el AD cae, usamos el último valor conocido (aunque haya expirado).
            if hit:
                log.warning("ad.group_members_stale", group=group)
                return hit.value
            raise
        self._cache[key] = _CacheEntry(emails, now + self.cfg.group_cache_seconds)
        return emails

    async def search_groups(self, query: str, limit: int = 20) -> list[DirectoryGroup]:
        q = _escape(query.strip()) if query.strip() else ""
        flt = f"(&(objectClass=group)(cn=*{q}*))" if q else "(objectClass=group)"
        rows = await self._run(self._paged, self._group_base(), flt, ["cn", "distinguishedName"])
        groups = [
            DirectoryGroup(nombre=str(_first(r, "cn")), dn=str(_first(r, "distinguishedName")))
            for r in rows if _first(r, "cn")
        ]
        return sorted(groups, key=lambda g: g.nombre.lower())[:limit]


# =========================================================================
# Factoría (config efectiva interfaz/entorno; override para tests)
# =========================================================================
_client: LdapDirectoryClient | None = None
_client_fp: tuple | None = None
_override: DirectoryClient | None = None


async def get_directory_client(db=None) -> DirectoryClient | None:
    """Cliente activo según la config efectiva, o None si AD no está habilitado."""
    global _client, _client_fp
    if _override is not None:
        return _override
    from app.services.integration_config import get_config
    cfg = (await get_config(db)).ad
    if not cfg.ready:
        return None
    # Un cambio de configuración crea un cliente nuevo (y vacía la caché de grupos).
    if _client is None or _client_fp != cfg.fingerprint():
        _client, _client_fp = LdapDirectoryClient(cfg), cfg.fingerprint()
    else:
        _client.cfg = cfg
    return _client


def set_directory_client(client: DirectoryClient | None) -> None:
    """Inyecta un cliente (tests). None restaura el comportamiento normal."""
    global _override
    _override = client
