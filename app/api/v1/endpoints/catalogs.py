from typing import List
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.catalogs import CatalogService
from app.schemas.catalogs import (
    TipoActivoCreate, TipoActivoResponse,
    MarcaCreate, MarcaResponse,
    TipoConexionCreate, TipoConexionResponse,
    ModeloCreate, ModeloResponse,
    EstadoOperativoCreate, EstadoOperativoResponse,
    TipoEspecificacionCreate, TipoEspecificacionResponse
)

router = APIRouter()

def get_service(db: AsyncSession = Depends(get_db)) -> CatalogService:
    return CatalogService(db)

# ================= TIPO DE ACTIVO =================
@router.post("/tipos-activo", response_model=TipoActivoResponse, status_code=201)
async def create_tipo_activo(schema: TipoActivoCreate, service: CatalogService = Depends(get_service)):
    return await service.create_tipo_activo(schema)

@router.get("/tipos-activo", response_model=List[TipoActivoResponse])
async def list_tipos_activo(service: CatalogService = Depends(get_service)):
    return await service.list_tipos_activo()

# ================= MARCA =================
@router.post("/marcas", response_model=MarcaResponse, status_code=201)
async def create_marca(schema: MarcaCreate, service: CatalogService = Depends(get_service)):
    return await service.create_marca(schema)

@router.get("/marcas", response_model=List[MarcaResponse])
async def list_marcas(service: CatalogService = Depends(get_service)):
    return await service.list_marcas()

# ================= TIPO CONEXIÓN =================
@router.post("/tipos-conexion", response_model=TipoConexionResponse, status_code=201)
async def create_tipo_conexion(schema: TipoConexionCreate, service: CatalogService = Depends(get_service)):
    return await service.create_tipo_conexion(schema)

@router.get("/tipos-conexion", response_model=List[TipoConexionResponse])
async def list_tipos_conexion(service: CatalogService = Depends(get_service)):
    return await service.list_tipos_conexion()

# ================= MODELO =================
@router.post("/modelos", response_model=ModeloResponse, status_code=201)
async def create_modelo(schema: ModeloCreate, service: CatalogService = Depends(get_service)):
    return await service.create_modelo(schema)

@router.get("/modelos", response_model=List[ModeloResponse])
async def list_modelos(marca_id: int = Query(..., description="ID de la Marca"), service: CatalogService = Depends(get_service)):
    return await service.list_modelos(marca_id)

# ================= ESTADO OPERATIVO =================
@router.post("/estados-operativos", response_model=EstadoOperativoResponse, status_code=201)
async def create_estado_operativo(schema: EstadoOperativoCreate, service: CatalogService = Depends(get_service)):
    return await service.create_estado_operativo(schema)

@router.get("/estados-operativos", response_model=List[EstadoOperativoResponse])
async def list_estados_operativos(service: CatalogService = Depends(get_service)):
    return await service.list_estados_operativos()

# ================= TIPO ESPECIFICACIÓN =================
@router.post("/tipos-especificacion", response_model=TipoEspecificacionResponse, status_code=201)
async def create_tipo_especificacion(schema: TipoEspecificacionCreate, service: CatalogService = Depends(get_service)):
    return await service.create_tipo_especificacion(schema)

@router.get("/tipos-especificacion", response_model=List[TipoEspecificacionResponse])
async def list_tipos_especificacion(service: CatalogService = Depends(get_service)):
    return await service.list_tipos_especificacion()