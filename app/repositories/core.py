from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import update, func
from typing import List, Optional
import uuid

from app.models.core import Activo, Especificacion
from app.schemas.core import ActivoCreate, EspecificacionCreate, ActivoUpdate

class CoreRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_codigo_interno(self, codigo: str) -> Optional[Activo]:
        result = await self.db.execute(select(Activo).where(Activo.ACT_Codigo_Interno == codigo))
        return result.scalar_one_or_none()

    async def get_by_serie(self, serie: str) -> Optional[Activo]:
        result = await self.db.execute(select(Activo).where(Activo.ACT_Serie_Fabricante == serie))
        return result.scalar_one_or_none()
    
    async def get_by_id(self, id: uuid.UUID) -> Optional[Activo]:
        result = await self.db.execute(select(Activo).where(Activo.ACT_Activo == id))
        return result.scalar_one_or_none()

    async def create_activo(self, schema: ActivoCreate) -> Activo:
        # 1. Preparamos datos del activo
        activo_data = schema.model_dump(exclude={"especificaciones"})
        db_activo = Activo(**activo_data)
        
        # 2. Agregamos el activo a la sesión
        self.db.add(db_activo)
        
        # 3. Procesamos especificaciones anidadas
        if schema.especificaciones:
            for spec_schema in schema.especificaciones:
                db_spec = Especificacion(
                    **spec_schema.model_dump(),
                    activo=db_activo 
                )
                self.db.add(db_spec)

        # 4. Commit Atómico
        await self.db.commit()
        
        # 5. Refrescamos para cargar relaciones
        query = (
            select(Activo)
            .options(selectinload(Activo.especificaciones))
            .where(Activo.ACT_Activo == db_activo.ACT_Activo)
        )
        result = await self.db.execute(query)
        return result.scalar_one()

    async def update_activo(self, id: uuid.UUID, schema: ActivoUpdate) -> Activo:
        update_data = schema.model_dump(exclude_unset=True)
        
        if not update_data:
            return await self.get_by_id(id)

        query = (
            update(Activo)
            .where(Activo.ACT_Activo == id)
            .values(**update_data)
        )
        await self.db.execute(query)
        await self.db.commit()
        return await self.get_by_id(id)

    async def get_all(self, skip: int = 0, limit: int = 100) -> List[Activo]:
        query = select(Activo).options(selectinload(Activo.especificaciones)).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def count_activos(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(Activo))
        return result.scalar() or 0

    async def count_activos_by_estado(self, estado_id: int) -> int:
        result = await self.db.execute(select(func.count()).select_from(Activo).where(Activo.EOP_Estado_Operativo == estado_id))
        return result.scalar() or 0