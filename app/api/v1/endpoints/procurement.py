"""Compras: Proveedores, Órdenes de Compra y vista de Garantías."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_client_ip, require_admin
from app.core.limiter import limiter
from app.db.session import get_db
from app.schemas.procurement import (
    GarantiaItem, OrdenCreate, OrdenDetalleResponse, OrdenEstadoUpdate, OrdenResponse,
    ProveedorCreate, ProveedorResponse, ProveedorUpdate, RecepcionOrden, RecepcionResultado,
)
from app.services.procurement import ProcurementService

router = APIRouter()

ADMIN = [Depends(require_admin)]


def get_service(db: AsyncSession = Depends(get_db)) -> ProcurementService:
    return ProcurementService(db)


def _ctx(request: Request, user: CurrentUser) -> dict:
    return {"usuario_id": user.USU_Usuario, "ip": get_client_ip(request)}


# ================= PROVEEDORES =================
@router.get("/proveedores", response_model=List[ProveedorResponse])
async def list_proveedores(
    solo_activos: bool = Query(False),
    service: ProcurementService = Depends(get_service),
):
    return await service.list_proveedores(solo_activos=solo_activos)


@router.get("/proveedores/{id}", response_model=ProveedorResponse)
async def get_proveedor(id: int, service: ProcurementService = Depends(get_service)):
    return await service.get_proveedor(id)


@router.post("/proveedores", response_model=ProveedorResponse, status_code=201, dependencies=ADMIN)
async def create_proveedor(
    schema: ProveedorCreate, request: Request, current_user: CurrentUser,
    service: ProcurementService = Depends(get_service),
):
    return await service.create_proveedor(schema, **_ctx(request, current_user))


@router.patch("/proveedores/{id}", response_model=ProveedorResponse, dependencies=ADMIN)
async def update_proveedor(
    id: int, schema: ProveedorUpdate, request: Request, current_user: CurrentUser,
    service: ProcurementService = Depends(get_service),
):
    return await service.update_proveedor(id, schema, **_ctx(request, current_user))


@router.delete("/proveedores/{id}", status_code=204, dependencies=ADMIN)
async def delete_proveedor(
    id: int, request: Request, current_user: CurrentUser,
    service: ProcurementService = Depends(get_service),
):
    await service.delete_proveedor(id, **_ctx(request, current_user))


# ================= ÓRDENES DE COMPRA =================
@router.get("/ordenes", response_model=List[OrdenResponse])
async def list_ordenes(
    estado: Optional[str] = Query(None),
    service: ProcurementService = Depends(get_service),
):
    return await service.list_ordenes(estado=estado)


@router.get("/ordenes/{id}", response_model=OrdenDetalleResponse)
async def get_orden(id: int, service: ProcurementService = Depends(get_service)):
    return await service.get_orden(id)


@router.post("/ordenes", response_model=OrdenDetalleResponse, status_code=201, dependencies=ADMIN)
@limiter.limit("30/minute")
async def create_orden(
    schema: OrdenCreate, request: Request, current_user: CurrentUser,
    service: ProcurementService = Depends(get_service),
):
    return await service.create_orden(schema, **_ctx(request, current_user))


@router.patch("/ordenes/{id}/estado", response_model=OrdenDetalleResponse, dependencies=ADMIN)
async def cambiar_estado_orden(
    id: int, schema: OrdenEstadoUpdate, request: Request, current_user: CurrentUser,
    service: ProcurementService = Depends(get_service),
):
    return await service.cambiar_estado(id, schema.OCO_Estado, **_ctx(request, current_user))


@router.post("/ordenes/{id}/recibir", response_model=RecepcionResultado, dependencies=ADMIN)
@limiter.limit("30/minute")
async def recibir_orden(
    id: int, schema: RecepcionOrden, request: Request, current_user: CurrentUser,
    service: ProcurementService = Depends(get_service),
):
    """
    Recibe la orden (lazo cerrado): suma el stock de los consumibles indicados
    y da de alta los activos indicados (enlazándolos a la orden → alimenta la
    vista de garantías). Marca la orden como RECIBIDA. Todo en una transacción.
    """
    return await service.recibir_orden(id, schema, **_ctx(request, current_user))


# ================= GARANTÍAS =================
@router.get("/garantias", response_model=List[GarantiaItem])
async def list_garantias(
    dias: int = Query(90, ge=1, le=3650, description="Ventana de 'por vencer' en días"),
    solo_alertas: bool = Query(False, description="Solo por_vencer + vencida"),
    service: ProcurementService = Depends(get_service),
):
    return await service.garantias(dias=dias, solo_alertas=solo_alertas)


@router.post("/garantias/notificar", dependencies=ADMIN)
@limiter.limit("10/minute")
async def notificar_garantias(
    request: Request, current_user: CurrentUser,
    dias: int = Query(90, ge=1, le=3650),
    service: ProcurementService = Depends(get_service),
):
    """Envía a los admins un digest de garantías por vencer/vencidas (a demanda o vía cron)."""
    return await service.notificar_garantias(dias=dias)
