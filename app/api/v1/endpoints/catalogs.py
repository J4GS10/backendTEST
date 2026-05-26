"""Catálogos técnicos. Lectura: cualquier autenticado. Mutación: ADMIN+."""
from typing import List
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_client_ip, require_admin
from app.db.session import get_db
from app.schemas.catalogs import (
    EstadoOperativoCreate, EstadoOperativoResponse, EstadoOperativoUpdate,
    MarcaCreate, MarcaResponse, MarcaUpdate,
    ModeloCreate, ModeloFlatResponse, ModeloResponse, ModeloUpdate,
    TipoActivoCreate, TipoActivoResponse, TipoActivoUpdate,
    TipoConexionCreate, TipoConexionResponse, TipoConexionUpdate,
    TipoEspecificacionCreate, TipoEspecificacionResponse, TipoEspecificacionUpdate,
)
from app.services.catalogs import CatalogService

router = APIRouter()

WRITE = [Depends(require_admin)]


def get_service(db: AsyncSession = Depends(get_db)) -> CatalogService:
    return CatalogService(db)


# ================= TIPO DE ACTIVO =================
@router.post("/tipos-activo", response_model=TipoActivoResponse, status_code=201, dependencies=WRITE)
async def create_tipo_activo(
    schema: TipoActivoCreate, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    return await service.create_tipo_activo(schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


@router.get("/tipos-activo", response_model=List[TipoActivoResponse])
async def list_tipos_activo(service: CatalogService = Depends(get_service)):
    return await service.list_tipos_activo()


@router.get("/tipos-activo/{id}", response_model=TipoActivoResponse)
async def get_tipo_activo(id: int, service: CatalogService = Depends(get_service)):
    return await service.get_tipo_activo(id)


@router.patch("/tipos-activo/{id}", response_model=TipoActivoResponse, dependencies=WRITE)
async def update_tipo_activo(
    id: int, schema: TipoActivoUpdate, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    return await service.update_tipo_activo(id, schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


@router.delete("/tipos-activo/{id}", status_code=204, dependencies=WRITE)
async def delete_tipo_activo(
    id: int, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    await service.delete_tipo_activo(id, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


# ================= MARCA =================
@router.post("/marcas", response_model=MarcaResponse, status_code=201, dependencies=WRITE)
async def create_marca(
    schema: MarcaCreate, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    return await service.create_marca(schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


@router.get("/marcas", response_model=List[MarcaResponse])
async def list_marcas(service: CatalogService = Depends(get_service)):
    return await service.list_marcas()


@router.get("/marcas/{id}", response_model=MarcaResponse)
async def get_marca(id: int, service: CatalogService = Depends(get_service)):
    return await service.get_marca(id)


@router.patch("/marcas/{id}", response_model=MarcaResponse, dependencies=WRITE)
async def update_marca(
    id: int, schema: MarcaUpdate, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    return await service.update_marca(id, schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


@router.delete("/marcas/{id}", status_code=204, dependencies=WRITE)
async def delete_marca(
    id: int, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    await service.delete_marca(id, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


# ================= TIPO CONEXIÓN =================
@router.post("/tipos-conexion", response_model=TipoConexionResponse, status_code=201, dependencies=WRITE)
async def create_tipo_conexion(
    schema: TipoConexionCreate, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    return await service.create_tipo_conexion(schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


@router.get("/tipos-conexion", response_model=List[TipoConexionResponse])
async def list_tipos_conexion(service: CatalogService = Depends(get_service)):
    return await service.list_tipos_conexion()


@router.get("/tipos-conexion/{id}", response_model=TipoConexionResponse)
async def get_tipo_conexion(id: int, service: CatalogService = Depends(get_service)):
    return await service.get_tipo_conexion(id)


@router.patch("/tipos-conexion/{id}", response_model=TipoConexionResponse, dependencies=WRITE)
async def update_tipo_conexion(
    id: int, schema: TipoConexionUpdate, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    return await service.update_tipo_conexion(id, schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


@router.delete("/tipos-conexion/{id}", status_code=204, dependencies=WRITE)
async def delete_tipo_conexion(
    id: int, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    await service.delete_tipo_conexion(id, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


# ================= MODELO =================
@router.post("/modelos", response_model=ModeloResponse, status_code=201, dependencies=WRITE)
async def create_modelo(
    schema: ModeloCreate, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    return await service.create_modelo(schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


@router.get("/modelos", response_model=List[ModeloResponse])
async def list_modelos(
    marca_id: int = Query(..., description="ID de la Marca"),
    service: CatalogService = Depends(get_service),
):
    return await service.list_modelos(marca_id)


@router.get("/modelos-flat", response_model=List[ModeloFlatResponse])
async def list_modelos_flat(
    q: str | None = Query(None, max_length=64, description="Filtro por nombre de modelo o marca"),
    limit: int = Query(500, ge=1, le=1000),
    service: CatalogService = Depends(get_service),
):
    """
    Devuelve modelos con marca embebida en una sola consulta. Pensado para
    selects del frontend (evita N requests, uno por cada marca).
    """
    return await service.list_modelos_flat(q=q, limit=limit)


@router.get("/modelos/{id}", response_model=ModeloResponse)
async def get_modelo(id: int, service: CatalogService = Depends(get_service)):
    return await service.get_modelo(id)


@router.patch("/modelos/{id}", response_model=ModeloResponse, dependencies=WRITE)
async def update_modelo(
    id: int, schema: ModeloUpdate, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    return await service.update_modelo(id, schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


@router.delete("/modelos/{id}", status_code=204, dependencies=WRITE)
async def delete_modelo(
    id: int, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    await service.delete_modelo(id, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


# ================= ESTADO OPERATIVO =================
@router.post("/estados-operativos", response_model=EstadoOperativoResponse, status_code=201, dependencies=WRITE)
async def create_estado_operativo(
    schema: EstadoOperativoCreate, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    return await service.create_estado_operativo(schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


@router.get("/estados-operativos", response_model=List[EstadoOperativoResponse])
async def list_estados_operativos(service: CatalogService = Depends(get_service)):
    return await service.list_estados_operativos()


@router.get("/estados-operativos/{id}", response_model=EstadoOperativoResponse)
async def get_estado_operativo(id: int, service: CatalogService = Depends(get_service)):
    return await service.get_estado_operativo(id)


@router.patch("/estados-operativos/{id}", response_model=EstadoOperativoResponse, dependencies=WRITE)
async def update_estado_operativo(
    id: int, schema: EstadoOperativoUpdate, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    return await service.update_estado_operativo(id, schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


@router.delete("/estados-operativos/{id}", status_code=204, dependencies=WRITE)
async def delete_estado_operativo(
    id: int, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    await service.delete_estado_operativo(id, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


# ================= TIPO ESPECIFICACIÓN =================
@router.post("/tipos-especificacion", response_model=TipoEspecificacionResponse, status_code=201, dependencies=WRITE)
async def create_tipo_especificacion(
    schema: TipoEspecificacionCreate, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    return await service.create_tipo_especificacion(schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


@router.get("/tipos-especificacion", response_model=List[TipoEspecificacionResponse])
async def list_tipos_especificacion(service: CatalogService = Depends(get_service)):
    return await service.list_tipos_especificacion()


@router.get("/tipos-especificacion/{id}", response_model=TipoEspecificacionResponse)
async def get_tipo_especificacion(id: int, service: CatalogService = Depends(get_service)):
    return await service.get_tipo_especificacion(id)


@router.patch("/tipos-especificacion/{id}", response_model=TipoEspecificacionResponse, dependencies=WRITE)
async def update_tipo_especificacion(
    id: int, schema: TipoEspecificacionUpdate, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    return await service.update_tipo_especificacion(id, schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))


@router.delete("/tipos-especificacion/{id}", status_code=204, dependencies=WRITE)
async def delete_tipo_especificacion(
    id: int, request: Request, current_user: CurrentUser,
    service: CatalogService = Depends(get_service),
):
    await service.delete_tipo_especificacion(id, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request))
