from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.traceability import TraceabilityService
from app.schemas.traceability import (
    TipoMovimientoCreate, TipoMovimientoResponse,
    MovimientoCreate, MovimientoResponse
)

router = APIRouter()

def get_service(db: AsyncSession = Depends(get_db)) -> TraceabilityService:
    return TraceabilityService(db)

# --- TIPOS DE MOVIMIENTO ---
@router.post("/tipos", response_model=TipoMovimientoResponse, status_code=201)
async def create_tipo_movimiento(schema: TipoMovimientoCreate, service: TraceabilityService = Depends(get_service)):
    return await service.create_tipo_movimiento(schema)

@router.get("/tipos", response_model=List[TipoMovimientoResponse])
async def list_tipos(service: TraceabilityService = Depends(get_service)):
    return await service.list_tipos_movimiento()

# --- TRANSACCIONES (ASIGNAR) ---
@router.post("/movimientos", response_model=MovimientoResponse, status_code=201)
async def registrar_movimiento(schema: MovimientoCreate, service: TraceabilityService = Depends(get_service)):
    """
    Registra un movimiento (Asignación/Préstamo).
    Automáticamente cierra cualquier asignación vigente previa del mismo activo.
    """
    return await service.registrar_movimiento(schema)