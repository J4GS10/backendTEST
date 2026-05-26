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
)
from app.services.core import CoreService

router = APIRouter()

OPERATIVO = [Depends(require_operativo)]
ADMIN = [Depends(require_admin)]


def get_service(db: AsyncSession = Depends(get_db)) -> CoreService:
    return CoreService(db)


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
