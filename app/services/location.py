from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.repositories.location import LocationRepository
from app.schemas.location import (
    PaisCreate, EstadoCreate, MunicipioCreate, 
    SedeCreate, EdificioCreate, NivelCreate, AreaCreate
)

class LocationService:
    def __init__(self, db: AsyncSession):
        self.repo = LocationRepository(db)

    # PAIS
    async def create_pais(self, schema: PaisCreate):
        return await self.repo.create_pais(schema)

    async def list_paises(self):
        return await self.repo.get_paises()

    # ESTADO
    async def create_estado(self, schema: EstadoCreate):
        return await self.repo.create_estado(schema)

    async def list_estados(self, pais_id: int):
        return await self.repo.get_estados_by_pais(pais_id)

    # MUNICIPIO
    async def create_municipio(self, schema: MunicipioCreate):
        return await self.repo.create_municipio(schema)

    async def list_municipios(self, estado_id: int):
        return await self.repo.get_municipios_by_estado(estado_id)

    # SEDE
    async def create_sede(self, schema: SedeCreate):
        return await self.repo.create_sede(schema)

    async def list_sedes(self, municipio_id: int):
        return await self.repo.get_sedes_by_municipio(municipio_id)

    # EDIFICIO
    async def create_edificio(self, schema: EdificioCreate):
        return await self.repo.create_edificio(schema)

    async def list_edificios(self, sede_id: int):
        return await self.repo.get_edificios_by_sede(sede_id)

    # NIVEL
    async def create_nivel(self, schema: NivelCreate):
        return await self.repo.create_nivel(schema)

    async def list_niveles(self, edificio_id: int):
        return await self.repo.get_niveles_by_edificio(edificio_id)

    # AREA
    async def create_area(self, schema: AreaCreate):
        return await self.repo.create_area(schema)
    
    async def list_areas(self, nivel_id: int):
        return await self.repo.get_areas_by_nivel(nivel_id)

    async def get_area_detail(self, area_id: int):
        area = await self.repo.get_area_by_id(area_id)
        if not area:
            raise HTTPException(status_code=404, detail="AREA_NOT_FOUND")
        return area