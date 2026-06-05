"""Activos (Core). Lectura: cualquier autenticado. Mutación: TECNICO+."""
from typing import List
import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, PaginationParams, get_client_ip, require_admin, require_operativo
from app.core.limiter import limiter
from app.db.session import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.core import (
    ActivoCreate, ActivoDetailResponse, ActivoFilter, ActivoResponse, ActivoUpdate,
    EspecificacionCreate, EspecificacionDetalle, EspecificacionValorUpdate,
)
from app.services.core import CoreService

router = APIRouter()

OPERATIVO = [Depends(require_operativo)]
ADMIN = [Depends(require_admin)]


def get_service(db: AsyncSession = Depends(get_db)) -> CoreService:
    return CoreService(db)


def _ctx(request: Request, user: CurrentUser) -> dict:
    return {"usuario_id": user.USU_Usuario, "ip": get_client_ip(request)}


# =====================================================================
# ESPECIFICACIONES (características del equipo: RAM, disco, batería, etc.)
# =====================================================================
@router.get("/activos/{activo_id}/especificaciones", response_model=List[EspecificacionDetalle])
async def list_especificaciones(activo_id: uuid.UUID, service: CoreService = Depends(get_service)):
    return await service.list_especificaciones(activo_id)


@router.post("/activos/{activo_id}/especificaciones", response_model=EspecificacionDetalle,
             status_code=201, dependencies=OPERATIVO)
async def add_especificacion(
    activo_id: uuid.UUID, schema: EspecificacionCreate, request: Request, current_user: CurrentUser,
    service: CoreService = Depends(get_service),
):
    await service.add_especificacion(
        activo_id, schema.TES_Tipo_Especificacion, schema.ESP_Valor, **_ctx(request, current_user)
    )
    # Devolvemos la fila enriquecida recién creada.
    specs = await service.list_especificaciones(activo_id)
    return next((s for s in specs if s["TES_Tipo_Especificacion"] == schema.TES_Tipo_Especificacion), specs[-1])


@router.patch("/especificaciones/{esp_id}", status_code=204, dependencies=OPERATIVO)
async def update_especificacion(
    esp_id: int, schema: EspecificacionValorUpdate, request: Request, current_user: CurrentUser,
    service: CoreService = Depends(get_service),
):
    await service.update_especificacion(esp_id, schema.ESP_Valor, **_ctx(request, current_user))


@router.delete("/especificaciones/{esp_id}", status_code=204, dependencies=OPERATIVO)
async def delete_especificacion(
    esp_id: int, request: Request, current_user: CurrentUser,
    service: CoreService = Depends(get_service),
):
    await service.delete_especificacion(esp_id, **_ctx(request, current_user))


@router.post("/activos", response_model=ActivoResponse, status_code=201, dependencies=OPERATIVO)
async def create_activo(
    schema: ActivoCreate, request: Request, current_user: CurrentUser,
    service: CoreService = Depends(get_service),
):
    return await service.create_activo(
        schema, usuario_id=current_user.USU_Usuario
    )


@router.patch("/activos/{activo_id}", response_model=ActivoResponse, dependencies=OPERATIVO)
async def update_activo(
    activo_id: uuid.UUID, schema: ActivoUpdate, request: Request, current_user: CurrentUser,
    service: CoreService = Depends(get_service),
):
    return await service.update_activo(activo_id, schema, usuario_id=current_user.USU_Usuario)


@router.get("/activos", response_model=List[ActivoResponse])
async def list_activos(
    pagination: PaginationParams = Depends(),
    service: CoreService = Depends(get_service),
):
    return await service.list_activos(pagination.skip, pagination.limit)


@router.get("/activos/{activo_id}", response_model=ActivoDetailResponse)
async def get_activo_detail(
    activo_id: uuid.UUID,
    service: CoreService = Depends(get_service),
):
    return await service.get_activo_detail(activo_id)


@router.delete("/activos/{activo_id}", status_code=204, dependencies=ADMIN)
async def delete_activo(
    activo_id: uuid.UUID, request: Request, current_user: CurrentUser,
    service: CoreService = Depends(get_service),
):
    """Baja lógica. Solo ADMIN+."""
    await service.delete_activo(activo_id, usuario_id=current_user.USU_Usuario)


@router.post("/activos/search", response_model=PaginatedResponse[ActivoResponse])
@limiter.limit("30/minute")
async def search_activos(
    request: Request,
    filters: ActivoFilter,
    service: CoreService = Depends(get_service),
):
    """
    Búsqueda paginada server-side. Devuelve {items, total, page, per_page}.
    El frontend usa `total` para calcular el número de páginas y mostrar el contador.
    """
    activos, total = await service.search_activos(filters)
    return PaginatedResponse[ActivoResponse](
        items=activos,
        total=total,
        page=filters.page,
        per_page=filters.per_page,
    )
