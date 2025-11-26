from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional

from app.models.catalogs import (
    TipoActivo, Marca, TipoConexion, Modelo, 
    EstadoOperativo, TipoEspecificacion
)
from app.schemas.catalogs import (
    TipoActivoCreate, MarcaCreate, TipoConexionCreate, 
    ModeloCreate, EstadoOperativoCreate, TipoEspecificacionCreate
)

class CatalogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- TIPO DE ACTIVO ---
    async def create_tipo_activo(self, schema: TipoActivoCreate) -> TipoActivo:
        db_obj = TipoActivo(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_tipos_activo(self) -> List[TipoActivo]:
        result = await self.db.execute(select(TipoActivo))
        return result.scalars().all()

    async def get_tipo_activo_by_name(self, name: str) -> Optional[TipoActivo]:
        result = await self.db.execute(select(TipoActivo).where(TipoActivo.TAC_Nombre == name))
        return result.scalar_one_or_none()

    # --- MARCA ---
    async def create_marca(self, schema: MarcaCreate) -> Marca:
        db_obj = Marca(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_marcas(self) -> List[Marca]:
        result = await self.db.execute(select(Marca))
        return result.scalars().all()
    
    async def get_marca_by_name(self, name: str) -> Optional[Marca]:
        result = await self.db.execute(select(Marca).where(Marca.MAR_Nombre == name))
        return result.scalar_one_or_none()

    # --- TIPO DE CONEXIÓN ---
    async def create_tipo_conexion(self, schema: TipoConexionCreate) -> TipoConexion:
        db_obj = TipoConexion(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_tipos_conexion(self) -> List[TipoConexion]:
        result = await self.db.execute(select(TipoConexion))
        return result.scalars().all()

    # --- MODELO ---
    async def create_modelo(self, schema: ModeloCreate) -> Modelo:
        db_obj = Modelo(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_modelos_by_marca(self, marca_id: int) -> List[Modelo]:
        result = await self.db.execute(select(Modelo).where(Modelo.MAR_Marca == marca_id))
        return result.scalars().all()

    # --- ESTADO OPERATIVO ---
    async def create_estado_operativo(self, schema: EstadoOperativoCreate) -> EstadoOperativo:
        db_obj = EstadoOperativo(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_estados_operativos(self) -> List[EstadoOperativo]:
        result = await self.db.execute(select(EstadoOperativo))
        return result.scalars().all()

    # --- TIPO DE ESPECIFICACIÓN ---
    async def create_tipo_especificacion(self, schema: TipoEspecificacionCreate) -> TipoEspecificacion:
        db_obj = TipoEspecificacion(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_tipos_especificacion(self) -> List[TipoEspecificacion]:
        result = await self.db.execute(select(TipoEspecificacion))
        return result.scalars().all()