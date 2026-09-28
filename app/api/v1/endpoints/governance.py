"""Gobernanza: configuración global y consulta de auditoría forense."""
from datetime import datetime
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_client_ip, require_audit_reader, require_super_admin
from app.core.limiter import limiter
from app.db.session import get_db, get_read_db
from app.schemas.governance import AuditoriaList, ConfigResponse, ConfigUpdate
from app.services.governance import GovernanceService

router = APIRouter()

SUPER = [Depends(require_super_admin)]
# Lectura de la auditoría: SUPER_ADMIN, ADMIN_SEGURIDAD y AUDITOR (este último
# solo ve los eventos de las sedes de su alcance y sus propias acciones).
AUDIT_READ = [Depends(require_audit_reader)]


def get_service(db: AsyncSession = Depends(get_db)) -> GovernanceService:
    return GovernanceService(db)


def get_read_service(db: AsyncSession = Depends(get_read_db)) -> GovernanceService:
    return GovernanceService(db)


# ================= CONFIG =================
@router.get("/config", response_model=ConfigResponse)
# Solo expone nombre, logo y colores. Cada carga del SPA lo pide; con 30/min por
# IP, una oficina detrás de un NAT compartido recibía 429 y la app perdía su
# paleta y su marca. 300/min sigue frenando scraping masivo.
@limiter.limit("300/minute")
async def get_config(request: Request, service: GovernanceService = Depends(get_service)):
    """
    Configuración pública (logo, colores) — accesible sin login para la pantalla
    de login. Rate-limit por IP para frenar scraping/fingerprinting masivo.
    """
    return await service.get_public_config()


@router.put("/config", response_model=ConfigResponse, dependencies=SUPER)
async def update_config(
    schema: ConfigUpdate, request: Request, current_user: CurrentUser,
    service: GovernanceService = Depends(get_service),
):
    return await service.update_config(
        schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request)
    )


# ================= MANTENIMIENTO DE SEGURIDAD =================
@router.post("/security/purge", dependencies=SUPER)
async def purge_security_records(service: GovernanceService = Depends(get_service)):
    """
    Limpia tokens revocados expirados e idempotency keys > 24h.
    Pensado para llamarse vía cron (ver scripts/purge_security.sh) o manualmente.
    """
    return await service.purge_security_records()


# ================= COLA DE CORREOS =================
@router.get("/email-outbox", dependencies=SUPER)
async def email_outbox_resumen(db: AsyncSession = Depends(get_db)):
    """Estado de la cola persistente de correos: conteos y últimos fallidos."""
    from app.services import email_outbox
    return await email_outbox.summary(db)


@router.post("/email-outbox/reintentar", dependencies=SUPER)
async def email_outbox_reintentar(
    outbox_id: Optional[uuid.UUID] = Query(None, description="Vacío = todos los FALLIDOS"),
    db: AsyncSession = Depends(get_db),
):
    from app.services import email_outbox
    return {"reencolados": await email_outbox.retry_failed(db, outbox_id)}


# ================= AUDITORÍA =================
@router.get("/auditoria", response_model=AuditoriaList, dependencies=AUDIT_READ)
async def list_auditoria(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    accion: Optional[str] = Query(None, description="CREATE | UPDATE | DELETE | DELETE_LOGIC | ASSIGN | ..."),
    entidad: Optional[str] = Query(None, description="Ej: INV_ACTIVO, INV_USUARIO"),
    usuario_id: Optional[uuid.UUID] = None,
    from_date: Optional[datetime] = Query(None, description="ISO timestamp inicial"),
    to_date: Optional[datetime] = Query(None, description="ISO timestamp final"),
    service: GovernanceService = Depends(get_read_service),
):
    """Consulta paginada del log forense (filtrada por el alcance del lector)."""
    return await service.list_audit_logs(
        skip=skip, limit=limit, accion=accion, entidad=entidad,
        usuario_id=usuario_id, from_date=from_date, to_date=to_date,
    )


@router.get("/auditoria/resumen", dependencies=AUDIT_READ)
@limiter.limit("10/minute")
async def auditoria_resumen(
    request: Request,
    from_date: Optional[datetime] = Query(None, description="ISO timestamp inicial"),
    to_date: Optional[datetime] = Query(None, description="ISO timestamp final"),
    service: GovernanceService = Depends(get_read_service),
):
    """
    Resumen agregado del log forense para dashboards: cuentas por acción y por entidad.
    Filtrado por el alcance del lector. Mucho más barato que paginar la tabla completa.
    """
    return await service.audit_summary(from_date=from_date, to_date=to_date)


# La exportación de la bitácora también se publica aquí: /export exige un rol
# de inventario y el administrador de seguridad no lo tiene.
from app.api.v1.endpoints.export import export_auditoria_csv  # noqa: E402

router.add_api_route(
    "/auditoria.csv", export_auditoria_csv, methods=["GET"], dependencies=AUDIT_READ,
    summary="Exportar la bitácora de auditoría (CSV)",
)
