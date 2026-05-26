"""Mantenimiento: tickets, tipos, detalles. RBAC granular."""
from typing import List
import uuid
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_client_ip, require_admin, require_operativo
from app.db.session import get_db
from app.schemas.maintenance import (
    DetalleCreate, DetalleResponse,
    MantenimientoCierre, MantenimientoCreate, MantenimientoResponse,
    TipoMantenimientoCreate, TipoMantenimientoResponse, TipoMantenimientoUpdate,
)
from app.services.maintenance import MaintenanceService

router = APIRouter()

ADMIN = [Depends(require_admin)]
OPERATIVO = [Depends(require_operativo)]


def get_service(db: AsyncSession = Depends(get_db)) -> MaintenanceService:
    return MaintenanceService(db)


def _ctx(request: Request, user: CurrentUser) -> dict:
    return {"usuario_id": user.USU_Usuario, "ip": get_client_ip(request)}


# ================= TIPOS DE MANTENIMIENTO =================
@router.get("/tipos", response_model=List[TipoMantenimientoResponse])
async def list_tipos(service: MaintenanceService = Depends(get_service)):
    return await service.list_tipos()


@router.get("/tipos/{id}", response_model=TipoMantenimientoResponse)
async def get_tipo(id: int, service: MaintenanceService = Depends(get_service)):
    return await service.get_tipo(id)


@router.post("/tipos", response_model=TipoMantenimientoResponse, status_code=201, dependencies=ADMIN)
async def create_tipo(
    schema: TipoMantenimientoCreate, request: Request, current_user: CurrentUser,
    service: MaintenanceService = Depends(get_service),
):
    return await service.create_tipo(schema, **_ctx(request, current_user))


@router.patch("/tipos/{id}", response_model=TipoMantenimientoResponse, dependencies=ADMIN)
async def update_tipo(
    id: int, schema: TipoMantenimientoUpdate, request: Request, current_user: CurrentUser,
    service: MaintenanceService = Depends(get_service),
):
    return await service.update_tipo(id, schema, **_ctx(request, current_user))


@router.delete("/tipos/{id}", status_code=204, dependencies=ADMIN)
async def delete_tipo(
    id: int, request: Request, current_user: CurrentUser,
    service: MaintenanceService = Depends(get_service),
):
    await service.delete_tipo(id, **_ctx(request, current_user))


# ================= TICKETS DE MANTENIMIENTO =================
@router.get("/", response_model=List[MantenimientoResponse])
async def list_mantenimientos(service: MaintenanceService = Depends(get_service)):
    return await service.list_mantenimientos()


@router.get("/{id}", response_model=MantenimientoResponse)
async def get_mantenimiento(id: uuid.UUID, service: MaintenanceService = Depends(get_service)):
    return await service.get_mantenimiento(id)


@router.post("/", response_model=MantenimientoResponse, status_code=201, dependencies=OPERATIVO)
async def registrar_mantenimiento(
    schema: MantenimientoCreate, request: Request, current_user: CurrentUser,
    service: MaintenanceService = Depends(get_service),
):
    return await service.registrar_mantenimiento(schema, **_ctx(request, current_user))


@router.patch("/{mantenimiento_id}/cerrar", response_model=MantenimientoResponse, dependencies=OPERATIVO)
async def cerrar_mantenimiento(
    mantenimiento_id: uuid.UUID, schema: MantenimientoCierre,
    request: Request, current_user: CurrentUser,
    service: MaintenanceService = Depends(get_service),
):
    return await service.cerrar_mantenimiento(mantenimiento_id, schema, **_ctx(request, current_user))


@router.delete("/{mantenimiento_id}", status_code=204, dependencies=ADMIN)
async def delete_mantenimiento(
    mantenimiento_id: uuid.UUID, request: Request, current_user: CurrentUser,
    service: MaintenanceService = Depends(get_service),
):
    """Borra un ticket SOLO si está cerrado (preserva integridad histórica)."""
    await service.delete_mantenimiento(mantenimiento_id, **_ctx(request, current_user))


# ================= DETALLES (items) =================
@router.get("/{mantenimiento_id}/detalles", response_model=List[DetalleResponse])
async def list_detalles(mantenimiento_id: uuid.UUID, service: MaintenanceService = Depends(get_service)):
    return await service.list_detalles(mantenimiento_id)


@router.post("/{mantenimiento_id}/detalles", response_model=DetalleResponse, status_code=201, dependencies=OPERATIVO)
async def agregar_detalle(
    mantenimiento_id: uuid.UUID, schema: DetalleCreate,
    request: Request, current_user: CurrentUser,
    service: MaintenanceService = Depends(get_service),
):
    return await service.agregar_detalle(mantenimiento_id, schema, **_ctx(request, current_user))


@router.patch("/detalles/{detalle_id}", response_model=DetalleResponse, dependencies=OPERATIVO)
async def update_detalle(
    detalle_id: int, schema: DetalleCreate,
    request: Request, current_user: CurrentUser,
    service: MaintenanceService = Depends(get_service),
):
    return await service.update_detalle(detalle_id, schema, **_ctx(request, current_user))


@router.delete("/detalles/{detalle_id}", status_code=204, dependencies=OPERATIVO)
async def delete_detalle(
    detalle_id: int, request: Request, current_user: CurrentUser,
    service: MaintenanceService = Depends(get_service),
):
    await service.delete_detalle(detalle_id, **_ctx(request, current_user))
