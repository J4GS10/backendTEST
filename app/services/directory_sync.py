"""
Sincronización de personas desde Active Directory.

Active Directory es la fuente de verdad para las personas vinculadas
(PER_AD_GUID): nombres, email, teléfono, departamento, cargo y jefe se
sobrescriben en cada sincronización.

Reglas:
- Vinculación: por objectGUID; si la persona aún no está vinculada, por email.
- Alta: usuarios habilitados de AD sin persona → nueva persona. Departamento
  y cargo se crean si no existen (por nombre, sin distinguir mayúsculas).
- Baja: cuentas deshabilitadas en AD, o vinculadas que ya no aparecen en la
  búsqueda → la persona (y su usuario del sistema) se desactiva SOLO si no
  tiene activos asignados. Si tiene activos queda en `pendientes_con_activos`
  y se avisa a los admins: la devolución debe hacerse con offboarding.
- Reactivación: cuenta habilitada de nuevo en AD → persona activa (el usuario
  del sistema NO se reactiva automáticamente).
- Jefe: atributo `manager` (DN) → PER_Jefe.
- `dry_run=True` calcula todo y hace rollback.
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.active_directory import DirectoryAuthError, DirectoryClient, DirectoryError, DirectoryUser, get_directory_client
from app.services.integration_config import AdConfig, get_config
from app.models.governance import AuditoriaSistema
from app.models.organization import Cargo, Departamento, Persona, Usuario
from app.models.traceability import Movimiento
from app.repositories.governance import GovernanceRepository

log = structlog.get_logger("directory_sync")

AUDIT_ACTION = "AD_SYNC"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _split(value: str | None, limit: int = 50) -> tuple[str | None, str | None]:
    """'Juan Carlos' → ('Juan', 'Carlos')."""
    parts = (value or "").split(None, 1)
    first = parts[0][:limit] if parts else None
    second = parts[1][:limit] if len(parts) > 1 else None
    return first, second


def _full_name(p: Persona) -> str:
    return f"{p.PER_Primer_Nombre} {p.PER_Primer_Apellido}"


class DirectorySyncService:
    def __init__(self, db: AsyncSession, directory: DirectoryClient | None = None) -> None:
        self.db = db
        self.directory = directory
        self.gov_repo = GovernanceRepository(db)
        self.ad_cfg = AdConfig(enabled=False)

    # ---- catálogos -------------------------------------------------------
    async def _catalog(self, model, name_col: str) -> dict[str, Any]:
        rows = (await self.db.execute(select(model))).scalars().all()
        return {getattr(r, name_col).lower(): r for r in rows}

    async def _get_or_create(self, cache: dict, model, name_col: str, name: str, extra: dict | None = None):
        name = name.strip()[:100]
        hit = cache.get(name.lower())
        if hit is None:
            hit = model(**{name_col: name, **(extra or {})})
            self.db.add(hit)
            await self.db.flush()
            cache[name.lower()] = hit
        return hit

    async def _active_assets(self, persona_id: uuid.UUID) -> int:
        return (await self.db.execute(
            select(func.count()).select_from(Movimiento).where(
                Movimiento.PER_Persona == persona_id,
                Movimiento.MOV_Fecha_Devolucion.is_(None),
            )
        )).scalar_one()

    # ---- aplicar atributos de AD a una persona ----------------------------
    async def _apply(self, p: Persona, u: DirectoryUser, deps: dict, cargos: dict) -> bool:
        primer_nombre, segundo_nombre = _split(u.given_name or u.username)
        primer_apellido, segundo_apellido = _split(u.surname or "-")
        dep = await self._get_or_create(
            deps, Departamento, "DEP_Nombre", u.department or self.ad_cfg.default_department,
        )
        car = await self._get_or_create(
            cargos, Cargo, "CAR_Nombre", u.title or self.ad_cfg.default_cargo,
        )
        values = {
            "PER_Primer_Nombre": primer_nombre or "-",
            "PER_Segundo_Nombre": segundo_nombre,
            "PER_Primer_Apellido": primer_apellido or "-",
            "PER_Segundo_Apellido": segundo_apellido,
            "PER_Email_Corporativo": u.email,
            "PER_Telefono": (u.phone or None) and u.phone[:20],
            "DEP_Departamento": dep.DEP_Departamento,
            "CAR_Cargo": car.CAR_Cargo,
            "PER_AD_GUID": u.guid,
            "PER_AD_DN": u.dn[:500],
        }
        changed = False
        for k, v in values.items():
            if getattr(p, k) != v:
                setattr(p, k, v)
                changed = True
        p.PER_AD_Sincronizado_En = _now()
        return changed

    # ---- sincronización ---------------------------------------------------
    async def sync(
        self, dry_run: bool = False, usuario_id: uuid.UUID | None = None, ip: str | None = None,
    ) -> dict[str, Any]:
        self.ad_cfg = (await get_config(self.db)).ad
        if self.directory is None:
            self.directory = await get_directory_client(self.db)
        if self.directory is None:
            raise HTTPException(400, detail="AD_DISABLED")
        try:
            users = await self.directory.list_users()
        except DirectoryAuthError as e:
            log.warning("ad_sync.auth_error", error=str(e))
            raise HTTPException(502, detail="AD_AUTH_FAILED") from e
        except DirectoryError as e:
            log.warning("ad_sync.directory_error", error=str(e))
            raise HTTPException(502, detail="AD_UNAVAILABLE") from e

        personas = (await self.db.execute(select(Persona))).scalars().all()
        by_guid = {p.PER_AD_GUID: p for p in personas if p.PER_AD_GUID}
        by_email = {p.PER_Email_Corporativo.lower(): p for p in personas}
        deps = await self._catalog(Departamento, "DEP_Nombre")
        cargos = await self._catalog(Cargo, "CAR_Nombre")

        result: dict[str, Any] = {
            "fecha": _now().isoformat(), "dry_run": dry_run, "total_ad": len(users),
            "creados": 0, "actualizados": 0, "vinculados": 0, "desactivados": 0,
            "reactivados": 0, "jefes_asignados": 0,
            "pendientes_con_activos": [], "errores": [],
        }
        seen_guids: set[str] = set()
        seen_emails: set[str] = set()
        by_dn: dict[str, Persona] = {}
        managers: list[tuple[Persona, str | None]] = []
        to_deactivate: list[Persona] = []

        for u in users:
            if u.email:
                u = replace(u, email=u.email.strip().lower())
            if not u.email:
                result["errores"].append({"email": None, "detalle": f"SIN_EMAIL: {u.username or u.dn}"})
                continue
            if u.email in seen_emails:
                result["errores"].append({"email": u.email, "detalle": "EMAIL_DUPLICADO_EN_AD"})
                continue
            seen_emails.add(u.email)
            seen_guids.add(u.guid)

            p = by_guid.get(u.guid)
            if p is None:
                p = by_email.get(u.email)
                if p is not None and p.PER_AD_GUID and p.PER_AD_GUID != u.guid:
                    result["errores"].append({"email": u.email, "detalle": "EMAIL_VINCULADO_A_OTRA_CUENTA_AD"})
                    continue
            else:
                other = by_email.get(u.email)
                if other is not None and other is not p:
                    result["errores"].append({"email": u.email, "detalle": "EMAIL_EN_USO_POR_OTRA_PERSONA"})
                    continue

            if p is None:
                if not u.enabled:
                    continue  # no se crean personas para cuentas deshabilitadas
                p = Persona(PER_Persona=uuid.uuid4(), PER_Estado=True)
                # _apply antes de add(): puede hacer flush (alta de catálogos)
                # y la persona aún no tiene sus columnas NOT NULL.
                await self._apply(p, u, deps, cargos)
                self.db.add(p)
                result["creados"] += 1
            else:
                was_linked = p.PER_AD_GUID is not None
                old_email = p.PER_Email_Corporativo.lower()
                changed = await self._apply(p, u, deps, cargos)
                if not was_linked:
                    result["vinculados"] += 1
                elif changed:
                    result["actualizados"] += 1
                if old_email != u.email:
                    by_email.pop(old_email, None)
                if u.enabled and not p.PER_Estado and was_linked:
                    p.PER_Estado = True
                    result["reactivados"] += 1
            by_email[u.email] = p
            by_dn[u.dn.lower()] = p
            managers.append((p, u.manager_dn))
            if not u.enabled and p.PER_Estado:
                to_deactivate.append(p)

        # Vinculadas que ya no aparecen en AD (eliminadas o fuera del filtro).
        if self.ad_cfg.deactivate:
            to_deactivate += [
                p for g, p in by_guid.items() if g not in seen_guids and p.PER_Estado
            ]
            for p in to_deactivate:
                activos = await self._active_assets(p.PER_Persona)
                if activos:
                    result["pendientes_con_activos"].append({
                        "persona_id": str(p.PER_Persona), "nombre": _full_name(p),
                        "email": p.PER_Email_Corporativo, "activos": activos,
                    })
                    continue
                p.PER_Estado = False
                await self.db.execute(
                    Usuario.__table__.update()
                    .where(Usuario.PER_Persona == p.PER_Persona)
                    .values(USU_Estado=False)
                )
                result["desactivados"] += 1

        await self.db.flush()
        for p, manager_dn in managers:
            jefe = by_dn.get(manager_dn.lower()) if manager_dn else None
            jefe_id = jefe.PER_Persona if jefe is not None and jefe is not p else None
            if p.PER_Jefe != jefe_id:
                p.PER_Jefe = jefe_id
                result["jefes_asignados"] += 1

        if dry_run:
            await self.db.rollback()
            return result

        await self.gov_repo.create_audit_log(
            accion=AUDIT_ACTION, entidad="INV_PERSONA", snapshot=result,
            usuario_id=usuario_id, ip_origen=ip,
        )
        await self.db.commit()
        log.info("ad_sync.done", **{k: v for k, v in result.items() if isinstance(v, int)})

        if result["pendientes_con_activos"]:
            try:
                from app.core.email import send_notification
                await send_notification(
                    "ad_sync_pendientes",
                    {"total": len(result["pendientes_con_activos"]), "items": result["pendientes_con_activos"]},
                    to=(),
                )
            except Exception:  # noqa: BLE001
                log.warning("ad_sync.notify_failed")
        return result

    async def last_sync(self) -> dict[str, Any] | None:
        row = (await self.db.execute(
            select(AuditoriaSistema.AUD_Snapshot_JSON)
            .where(AuditoriaSistema.AUD_Accion == AUDIT_ACTION)
            .order_by(AuditoriaSistema.AUD_Fecha_Hora.desc())
            .limit(1)
        )).scalar_one_or_none()
        return row


# =========================================================================
# Sincronización periódica (ver app/services/scheduled_jobs.py)
# =========================================================================
async def sync_once() -> dict[str, Any]:
    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        return await DirectorySyncService(db).sync()
