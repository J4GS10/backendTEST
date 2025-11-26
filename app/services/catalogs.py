from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.repositories.catalogs import CatalogRepository
from app.schemas.catalogs import (
    TipoActivoCreate, MarcaCreate, TipoConexionCreate,
    ModeloCreate, EstadoOperativoCreate, TipoEspecificacionCreate
)

class CatalogService:
    def __init__(self, db: AsyncSession):
        self.repo = CatalogRepository(db)

    # --- TIPO DE ACTIVO ---
    async def create_tipo_activo(self, schema: TipoActivoCreate):
        exists = await self.repo.get_tipo_activo_by_name(schema.TAC_Nombre)
        if exists:
            raise HTTPException(status_code=400, detail="ASSET_TYPE_ALREADY_EXISTS")
        return await self.repo.create_tipo_activo(schema)

    async def list_tipos_activo(self):
        return await self.repo.get_tipos_activo()

    # --- MARCA ---
    async def create_marca(self, schema: MarcaCreate):
        exists = await self.repo.get_marca_by_name(schema.MAR_Nombre)
        if exists:
            raise HTTPException(status_code=400, detail="BRAND_ALREADY_EXISTS")
        return await self.repo.create_marca(schema)

    async def list_marcas(self):
        return await self.repo.get_marcas()

    # --- TIPO DE CONEXIÓN ---
    async def create_tipo_conexion(self, schema: TipoConexionCreate):
        return await self.repo.create_tipo_conexion(schema)

    async def list_tipos_conexion(self):
        return await self.repo.get_tipos_conexion()

    # --- MODELO ---
    async def create_modelo(self, schema: ModeloCreate):
        # Podríamos validar que la Marca exista, pero la FK de la BD ya protege esto.
        # Opcional: Validar unicidad de Modelo dentro de la misma Marca.
        return await self.repo.create_modelo(schema)

    async def list_modelos(self, marca_id: int):
        return await self.repo.get_modelos_by_marca(marca_id)

    # --- ESTADO OPERATIVO ---
    async def create_estado_operativo(self, schema: EstadoOperativoCreate):
        return await self.repo.create_estado_operativo(schema)

    async def list_estados_operativos(self):
        return await self.repo.get_estados_operativos()

    # --- TIPO DE ESPECIFICACIÓN ---
    async def create_tipo_especificacion(self, schema: TipoEspecificacionCreate):
        return await self.repo.create_tipo_especificacion(schema)

    async def list_tipos_especificacion(self):
        return await self.repo.get_tipos_especificacion()