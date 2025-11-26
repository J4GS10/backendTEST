from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.core import CoreService
from app.schemas.core import ActivoCreate, ActivoResponse

router = APIRouter()

def get_service(db: AsyncSession = Depends(get_db)) -> CoreService:
    return CoreService(db)

@router.post("/activos", response_model=ActivoResponse, status_code=status.HTTP_201_CREATED)
async def create_activo(
    schema: ActivoCreate, 
    service: CoreService = Depends(get_service)
):
    """
    Crea un nuevo activo con sus especificaciones técnicas opcionales.
    Valida unicidad de Serie y Código Interno.
    """
    return await service.create_activo(schema)

@router.get("/activos", response_model=List[ActivoResponse])
async def list_activos(
    skip: int = 0, 
    limit: int = 100, 
    service: CoreService = Depends(get_service)
):
    return await service.list_activos(skip, limit)