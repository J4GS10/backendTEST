from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.maintenance import MaintenanceService
from app.schemas.maintenance import (
    MantenimientoCreate, MantenimientoResponse,
    TipoMantenimientoCreate, TipoMantenimientoResponse
)

router = APIRouter()

def get_service(db: AsyncSession = Depends(get_db)) -> MaintenanceService:
    return MaintenanceService(db)

# --- TIPOS ---
@router.get("/tipos", response_model=List[TipoMantenimientoResponse])
async def list_tipos(service: MaintenanceService = Depends(get_service)):
    return await service.list_tipos()

@router.post("/tipos", response_model=TipoMantenimientoResponse)
async def create_tipo(schema: TipoMantenimientoCreate, service: MaintenanceService = Depends(get_service)):
    return await service.create_tipo(schema)

# --- TICKETS ---
@router.get("/", response_model=List[MantenimientoResponse])
async def list_mantenimientos(service: MaintenanceService = Depends(get_service)):
    return await service.list_mantenimientos()

@router.post("/", response_model=MantenimientoResponse, status_code=201)
async def registrar_mantenimiento(schema: MantenimientoCreate, service: MaintenanceService = Depends(get_service)):
    return await service.registrar_mantenimiento(schema)