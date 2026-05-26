"""Gobernanza: configuración global y consulta de auditoría forense."""
from datetime import datetime
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_client_ip, require_super_admin
from app.core.limiter import limiter
from app.db.session import get_db
from app.schemas.governance import AuditoriaList, ConfigResponse, ConfigUpdate
from app.services.governance import GovernanceService

router = APIRouter()

SUPER = [Depends(require_super_admin)]


def get_service(db: AsyncSession = Depends(get_db)) -> GovernanceService:
    return GovernanceService(db)


# ================= CONFIG =================
@router.get("/config", response_model=ConfigResponse)
@limiter.limit("30/minute")
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
async def purge_security_records(db: AsyncSession = Depends(get_db)):
    """
    Limpia tokens revocados expirados e idempotency keys > 24h.
    Pensado para llamarse vía cron (ver scripts/purge_security.sh) o manualmente.
    """
    from app.repositories.governance import GovernanceRepository
    repo = GovernanceRepository(db)
    return await repo.purge_expired_security_records()


# ================= AUDITORÍA =================
@router.get("/auditoria", response_model=AuditoriaList, dependencies=SUPER)
async def list_auditoria(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    accion: Optional[str] = Query(None, description="CREATE | UPDATE | DELETE | DELETE_LOGIC | ASSIGN | ..."),
    entidad: Optional[str] = Query(None, description="Ej: INV_ACTIVO, INV_USUARIO"),
    usuario_id: Optional[uuid.UUID] = None,
    from_date: Optional[datetime] = Query(None, description="ISO timestamp inicial"),
    to_date: Optional[datetime] = Query(None, description="ISO timestamp final"),
    service: GovernanceService = Depends(get_service),
):
    """Consulta paginada del log forense. Solo SUPER_ADMIN."""
    return await service.list_audit_logs(
        skip=skip, limit=limit, accion=accion, entidad=entidad,
        usuario_id=usuario_id, from_date=from_date, to_date=to_date,
    )


@router.get("/auditoria/resumen", dependencies=SUPER)
@limiter.limit("10/minute")
async def auditoria_resumen(
    request: Request,
    from_date: Optional[datetime] = Query(None, description="ISO timestamp inicial"),
    to_date: Optional[datetime] = Query(None, description="ISO timestamp final"),
    service: GovernanceService = Depends(get_service),
):
    """
    Resumen agregado del log forense para dashboards: cuentas por acción y por entidad.
    Solo SUPER_ADMIN. Mucho más barato que paginar la tabla completa.
    """
    return await service.audit_summary(from_date=from_date, to_date=to_date)
