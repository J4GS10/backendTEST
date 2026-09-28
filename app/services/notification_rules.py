"""
Reglas de notificación por gestión + resolución de destinatarios.

Para cada evento configurable (asignación, devolución, offboarding, ...) una
regla decide a quién se envía el correo:

  afectado  → las personas involucradas en la gestión (p. ej. quien recibe el activo)
  jefe      → el jefe inmediato de cada afectado (PER_Jefe, sincronizado desde AD)
  admins    → NOTIFY_ADMIN_EMAILS + miembros del grupo AD_ADMIN_GROUP
  grupos_ad → miembros (transitivos) de grupos de Active Directory
  extra     → correos fijos

Si no hay fila en INV_REGLA_NOTIFICACION se aplican los valores por defecto,
que reproducen el comportamiento histórico del sistema. Los correos de
seguridad (reset/cambio de contraseña, códigos 2FA) NO son configurables.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Iterable

import structlog
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.transactional import transactional
from app.integrations.active_directory import DirectoryClient, DirectoryError, get_directory_client
from app.models.governance import ReglaNotificacion
from app.models.organization import Persona
from app.repositories.governance import GovernanceRepository

log = structlog.get_logger("notification_rules")


@dataclass(frozen=True)
class RuleDefaults:
    notificar_afectado: bool
    notificar_jefe: bool = False
    copiar_admins: bool = True


# Defaults = comportamiento previo a las reglas (quién recibía cada correo).
CONFIGURABLE_EVENTS: dict[str, RuleDefaults] = {
    "asignacion": RuleDefaults(notificar_afectado=True),
    "devolucion": RuleDefaults(notificar_afectado=True),
    "transferencia": RuleDefaults(notificar_afectado=True),
    "baja": RuleDefaults(notificar_afectado=False),
    "offboarding": RuleDefaults(notificar_afectado=False),
    "mantenimiento_abierto": RuleDefaults(notificar_afectado=True),
    "mantenimiento_cerrado": RuleDefaults(notificar_afectado=False),
    "stock_bajo": RuleDefaults(notificar_afectado=False),
    "garantia_por_vencer": RuleDefaults(notificar_afectado=False),
}


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _join(values: Iterable[str]) -> str | None:
    clean = []
    for v in values:
        v = v.strip()
        if v and v not in clean:
            clean.append(v)
    return ",".join(clean) or None


@dataclass
class RuleConfig:
    evento: str
    activa: bool
    notificar_afectado: bool
    notificar_jefe: bool
    copiar_admins: bool
    grupos_ad: list[str] = field(default_factory=list)
    correos_extra: list[str] = field(default_factory=list)
    personalizada: bool = False

    @classmethod
    def default(cls, evento: str) -> "RuleConfig":
        d = CONFIGURABLE_EVENTS[evento]
        return cls(
            evento=evento, activa=True,
            notificar_afectado=d.notificar_afectado,
            notificar_jefe=d.notificar_jefe,
            copiar_admins=d.copiar_admins,
        )

    @classmethod
    def from_row(cls, row: ReglaNotificacion) -> "RuleConfig":
        return cls(
            evento=row.RNO_Evento,
            activa=row.RNO_Activa,
            notificar_afectado=row.RNO_Notificar_Afectado,
            notificar_jefe=row.RNO_Notificar_Jefe,
            copiar_admins=row.RNO_Copiar_Admins,
            grupos_ad=_csv(row.RNO_Grupos_AD),
            correos_extra=[e.lower() for e in _csv(row.RNO_Correos_Extra)],
            personalizada=True,
        )


async def load_rule(db: AsyncSession, evento: str) -> RuleConfig:
    row = await db.get(ReglaNotificacion, evento)
    return RuleConfig.from_row(row) if row else RuleConfig.default(evento)


def static_admin_emails() -> list[str]:
    return [e.strip().lower() for e in (settings.NOTIFY_ADMIN_EMAILS or "").split(",") if e.strip()]


class RecipientResolver:
    """Calcula destinatarios (email → origen) para un evento según su regla."""

    _UNSET = object()

    def __init__(self, db: AsyncSession, directory: DirectoryClient | None = None) -> None:
        self.db = db
        self._directory = directory if directory is not None else self._UNSET

    async def _get_directory(self) -> DirectoryClient | None:
        if self._directory is self._UNSET:
            self._directory = await get_directory_client(self.db)
        return self._directory

    async def _group_emails(self, group: str) -> list[str]:
        directory = await self._get_directory()
        if not directory:
            return []
        try:
            return await directory.group_member_emails(group)
        except DirectoryError as e:
            log.warning("notification.group_lookup_failed", group=group, error=str(e))
            return []

    async def admin_emails(self) -> list[tuple[str, str]]:
        from app.services.integration_config import get_config
        out = [(e, "admins") for e in static_admin_emails()]
        admin_group = (await get_config(self.db)).ad.admin_group
        if admin_group:
            out += [(e, "admins") for e in await self._group_emails(admin_group)]
        return out

    async def manager_emails(self, affected: Iterable[str]) -> list[str]:
        emails = [e.lower() for e in affected if e]
        if not emails:
            return []
        jefe = Persona.__table__.alias("jefe")
        rows = await self.db.execute(
            select(jefe.c.PER_Email_Corporativo)
            .select_from(Persona)
            .join(jefe, jefe.c.PER_Persona == Persona.PER_Jefe)
            .where(func.lower(Persona.PER_Email_Corporativo).in_(emails))
            .where(jefe.c.PER_Estado.is_(True))
        )
        return [r[0].lower() for r in rows if r[0]]

    async def resolve(
        self,
        evento: str,
        *,
        to: Iterable[str] = (),
        affected: Iterable[str] | None = None,
        cc_admins: bool = True,
        rule: RuleConfig | None = None,
    ) -> list[tuple[str, str]]:
        """Lista ordenada y sin duplicados de (email, origen). [] si la regla está inactiva."""
        to = [e.lower() for e in to if e]
        affected_list = [e.lower() for e in affected if e] if affected is not None else to

        if evento not in CONFIGURABLE_EVENTS:
            pairs = [(e, "afectado") for e in to]
            if cc_admins:
                pairs += await self.admin_emails()
            return _dedupe(pairs)

        rule = rule or await load_rule(self.db, evento)
        if not rule.activa:
            return []
        pairs: list[tuple[str, str]] = []
        if rule.notificar_afectado:
            pairs += [(e, "afectado") for e in affected_list]
        if rule.notificar_jefe:
            pairs += [(e, "jefe") for e in await self.manager_emails(affected_list)]
        if rule.copiar_admins and cc_admins:
            pairs += await self.admin_emails()
        for g in rule.grupos_ad:
            pairs += [(e, f"grupo:{g}") for e in await self._group_emails(g)]
        pairs += [(e, "extra") for e in rule.correos_extra]
        return _dedupe(pairs)


def _dedupe(pairs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    for email, origen in pairs:
        if email and email not in seen:
            seen[email] = origen
    return list(seen.items())


# =========================================================================
# CRUD de reglas (API de configuración)
# =========================================================================
class NotificationRulesService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.gov_repo = GovernanceRepository(db)

    @staticmethod
    def _check_event(evento: str) -> None:
        if evento not in CONFIGURABLE_EVENTS:
            raise HTTPException(404, detail="NOTIFICATION_EVENT_NOT_FOUND")

    async def list_rules(self) -> list[RuleConfig]:
        rows = {r.RNO_Evento: r for r in (await self.db.execute(select(ReglaNotificacion))).scalars()}
        return [
            RuleConfig.from_row(rows[e]) if e in rows else RuleConfig.default(e)
            for e in CONFIGURABLE_EVENTS
        ]

    @transactional
    async def upsert_rule(
        self, evento: str, data: dict, usuario_id: uuid.UUID | None = None, ip: str | None = None,
    ) -> RuleConfig:
        self._check_event(evento)
        row = await self.db.get(ReglaNotificacion, evento)
        if row is None:
            row = ReglaNotificacion(RNO_Evento=evento)
            self.db.add(row)
        row.RNO_Activa = data["activa"]
        row.RNO_Notificar_Afectado = data["notificar_afectado"]
        row.RNO_Notificar_Jefe = data["notificar_jefe"]
        row.RNO_Copiar_Admins = data["copiar_admins"]
        row.RNO_Grupos_AD = _join(data.get("grupos_ad") or [])
        row.RNO_Correos_Extra = _join(e.lower() for e in (data.get("correos_extra") or []))
        await self.db.flush()
        await self.gov_repo.create_audit_log(
            accion="UPDATE", entidad="INV_REGLA_NOTIFICACION",
            snapshot={"evento": evento, **data}, usuario_id=usuario_id, ip_origen=ip,
        )
        return RuleConfig.from_row(row)

    @transactional
    async def reset_rule(
        self, evento: str, usuario_id: uuid.UUID | None = None, ip: str | None = None,
    ) -> None:
        self._check_event(evento)
        row = await self.db.get(ReglaNotificacion, evento)
        if row is not None:
            await self.db.delete(row)
            await self.gov_repo.create_audit_log(
                accion="DELETE", entidad="INV_REGLA_NOTIFICACION",
                snapshot={"evento": evento}, usuario_id=usuario_id, ip_origen=ip,
            )

    async def preview(self, evento: str, persona_id: uuid.UUID | None = None) -> list[tuple[str, str]]:
        self._check_event(evento)
        affected: list[str] = []
        if persona_id:
            persona = await self.db.get(Persona, persona_id)
            if not persona:
                raise HTTPException(404, detail="PERSON_NOT_FOUND")
            affected = [persona.PER_Email_Corporativo]
        return await RecipientResolver(self.db).resolve(evento, to=affected, affected=affected)
