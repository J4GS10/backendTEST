from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import desc
from typing import List
import uuid

from app.models.traceability import Mantenimiento, DetalleMantenimiento, TipoMantenimiento
from app.models.core import Activo
from app.models.organization import Persona
from app.schemas.maintenance import MantenimientoCreate, TipoMantenimientoCreate

class MaintenanceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- TIPOS ---
    async def create_tipo(self, schema: TipoMantenimientoCreate) -> TipoMantenimiento:
        db_obj = TipoMantenimiento(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_tipos(self) -> List[TipoMantenimiento]:
        result = await self.db.execute(select(TipoMantenimiento))
        return result.scalars().all()

    # --- MANTENIMIENTOS ---
    async def create_mantenimiento(self, schema: MantenimientoCreate) -> Mantenimiento:
        # 1. Datos Cabecera
        data = schema.model_dump(exclude={"detalles"})
        db_obj = Mantenimiento(**data)
        self.db.add(db_obj)
        
        # 2. Detalles (Items)
        if schema.detalles:
            for det in schema.detalles:
                db_det = DetalleMantenimiento(**det.model_dump(), mantenimiento=db_obj)
                self.db.add(db_det)
        
        await self.db.commit()
        
        # 3. Recargar con relaciones para devolver al frontend
        return await self.get_by_id(db_obj.MAN_Mantenimiento)

    async def get_all(self) -> List[Mantenimiento]:
        query = (
            select(Mantenimiento)
            .options(
                selectinload(Mantenimiento.tipo_mantenimiento),
                selectinload(Mantenimiento.activo).selectinload(Activo.modelo),
                selectinload(Mantenimiento.detalles)
            )
            .order_by(desc(Mantenimiento.MAN_Fecha_Ingreso))
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_by_id(self, id: uuid.UUID):
        query = (
            select(Mantenimiento)
            .options(
                selectinload(Mantenimiento.tipo_mantenimiento),
                selectinload(Mantenimiento.activo),
                selectinload(Mantenimiento.detalles)
            )
            .where(Mantenimiento.MAN_Mantenimiento == id)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()