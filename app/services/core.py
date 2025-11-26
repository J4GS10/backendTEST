from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.repositories.core import CoreRepository
from app.schemas.core import ActivoCreate

class CoreService:
    def __init__(self, db: AsyncSession):
        self.repo = CoreRepository(db)

    async def create_activo(self, schema: ActivoCreate):
        # Regla 1: El código interno (Placa) debe ser único
        if await self.repo.get_by_codigo_interno(schema.ACT_Codigo_Interno):
            raise HTTPException(status_code=400, detail="ASSET_CODE_ALREADY_EXISTS")
        
        # Regla 2: El número de serie (Fabricante) debe ser único
        if await self.repo.get_by_serie(schema.ACT_Serie_Fabricante):
            raise HTTPException(status_code=400, detail="SERIAL_NUMBER_ALREADY_EXISTS")

        # Aquí en el futuro inyectaremos la lógica de Trazabilidad (Movimiento Inicial)
        # Por ahora, creamos el registro maestro.
        return await self.repo.create_activo(schema)

    async def list_activos(self, skip: int, limit: int):
        return await self.repo.get_all(skip, limit)