from typing import List
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.software import SoftwareService
from app.schemas.software import (
    TipoLicenciaResponse, TipoLicenciaCreate,
    SoftwareResponse, SoftwareCreate,
    LicenciaResponse, LicenciaCreate,
    InstalacionResponse, InstalacionCreate
)

router = APIRouter()

def get_service(db: AsyncSession = Depends(get_db)) -> SoftwareService:
    return SoftwareService(db)

# --- TIPOS ---
@router.post("/tipos-licencia", response_model=TipoLicenciaResponse, status_code=201)
async def create_tipo_licencia(schema: TipoLicenciaCreate, service: SoftwareService = Depends(get_service)):
    return await service.create_tipo_licencia(schema)

@router.get("/tipos-licencia", response_model=List[TipoLicenciaResponse])
async def list_tipos_licencia(service: SoftwareService = Depends(get_service)):
    return await service.list_tipos_licencia()

# --- SOFTWARE ---
@router.post("/software", response_model=SoftwareResponse, status_code=201)
async def create_software(schema: SoftwareCreate, service: SoftwareService = Depends(get_service)):
    return await service.create_software(schema)

@router.get("/software", response_model=List[SoftwareResponse])
async def list_software(service: SoftwareService = Depends(get_service)):
    return await service.list_software()

# --- LICENCIAS ---
@router.post("/licencias", response_model=LicenciaResponse, status_code=201)
async def create_licencia(schema: LicenciaCreate, service: SoftwareService = Depends(get_service)):
    return await service.create_licencia(schema)

@router.get("/licencias", response_model=List[LicenciaResponse])
async def list_licencias(software_id: int = Query(...), service: SoftwareService = Depends(get_service)):
    return await service.list_licencias(software_id)

# --- INSTALACIONES (Operación) ---
@router.post("/instalaciones", response_model=InstalacionResponse, status_code=201)
async def registrar_instalacion(schema: InstalacionCreate, service: SoftwareService = Depends(get_service)):
    """
    Asigna una licencia a un activo.
    Valida automáticamente disponibilidad de cupos.
    """
    return await service.registrar_instalacion(schema)