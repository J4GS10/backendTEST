"""Consumibles: inventario por cantidad (tóner, cables, periféricos a granel)."""
from typing import List

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_client_ip, require_admin, require_operativo
from app.core.limiter import limiter
from app.db.session import get_db
from app.schemas.consumable import (
    ConsumibleCreate, ConsumibleResponse, ConsumibleUpdate,
    MovimientoConsumibleResponse, StockMovimientoCreate,
)
from app.services.consumable import ConsumableService

router = APIRouter()

ADMIN = [Depends(require_admin)]
OPERATIVO = [Depends(require_operativo)]


def get_service(db: AsyncSession = Depends(get_db)) -> ConsumableService:
    return ConsumableService(db)


def _ctx(request: Request, user: CurrentUser) -> dict:
    return {"usuario_id": user.USU_Usuario, "ip": get_client_ip(request)}


@router.get("", response_model=List[ConsumibleResponse])
async def list_consumibles(
    bajo_stock: bool = Query(False, description="Solo consumibles en o por debajo del mínimo"),
    service: ConsumableService = Depends(get_service),
):
    return await service.list(solo_bajo_stock=bajo_stock)


@router.get("/{id}", response_model=ConsumibleResponse)
async def get_consumible(id: int, service: ConsumableService = Depends(get_service)):
    return await service.get(id)


@router.post("", response_model=ConsumibleResponse, status_code=201, dependencies=ADMIN)
async def create_consumible(
    schema: ConsumibleCreate, request: Request, current_user: CurrentUser,
    service: ConsumableService = Depends(get_service),
):
    return await service.create(schema, **_ctx(request, current_user))


@router.patch("/{id}", response_model=ConsumibleResponse, dependencies=ADMIN)
async def update_consumible(
    id: int, schema: ConsumibleUpdate, request: Request, current_user: CurrentUser,
    service: ConsumableService = Depends(get_service),
):
    return await service.update(id, schema, **_ctx(request, current_user))


@router.delete("/{id}", status_code=204, dependencies=ADMIN)
async def delete_consumible(
    id: int, request: Request, current_user: CurrentUser,
    service: ConsumableService = Depends(get_service),
):
    await service.delete(id, **_ctx(request, current_user))


# ------------------------------------------------------------------
# Movimientos de stock
# ------------------------------------------------------------------
@router.post("/{id}/entrada", response_model=MovimientoConsumibleResponse, status_code=201, dependencies=OPERATIVO)
@limiter.limit("60/minute")
async def registrar_entrada(
    id: int, schema: StockMovimientoCreate, request: Request, current_user: CurrentUser,
    service: ConsumableService = Depends(get_service),
):
    """Suma stock al consumible (compra, reabastecimiento)."""
    return await service.registrar_entrada(id, schema, **_ctx(request, current_user))


@router.post("/{id}/salida", response_model=MovimientoConsumibleResponse, status_code=201, dependencies=OPERATIVO)
@limiter.limit("60/minute")
async def registrar_salida(
    id: int, schema: StockMovimientoCreate, request: Request, current_user: CurrentUser,
    service: ConsumableService = Depends(get_service),
):
    """Descuenta stock (entrega a una persona). 409 si no hay stock suficiente."""
    return await service.registrar_salida(id, schema, **_ctx(request, current_user))


@router.get("/{id}/movimientos", response_model=List[MovimientoConsumibleResponse])
async def list_movimientos(id: int, service: ConsumableService = Depends(get_service)):
    return await service.list_movimientos(id)
