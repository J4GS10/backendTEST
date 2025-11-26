from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, and_
from typing import Optional
from datetime import datetime
import uuid

from app.models.traceability import Movimiento, TipoMovimiento
from app.schemas.traceability import MovimientoCreate, TipoMovimientoCreate

class TraceabilityRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- TIPOS ---
    async def create_tipo_movimiento(self, schema: TipoMovimientoCreate) -> TipoMovimiento:
        db_obj = TipoMovimiento(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj
    
    async def get_tipos_movimiento(self):
        result = await self.db.execute(select(TipoMovimiento))
        return result.scalars().all()

    # --- MOVIMIENTOS ---
    
    async def get_movimiento_vigente(self, activo_id: uuid.UUID) -> Optional[Movimiento]:
        """Busca si el activo tiene una asignación abierta (Fecha Fin is NULL)"""
        query = select(Movimiento).where(
            and_(
                Movimiento.ACT_Activo == activo_id,
                Movimiento.MOV_Fecha_Devolucion == None
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def cerrar_movimiento(self, movimiento_id: uuid.UUID):
        """Cierra el ciclo de custodia anterior"""
        query = (
            update(Movimiento)
            .where(Movimiento.MOV_Movimiento == movimiento_id)
            .values(MOV_Fecha_Devolucion=datetime.now())
        )
        await self.db.execute(query)
        # No hacemos commit aquí, esperamos a la transacción completa en el Service

    async def create_movimiento_transactional(self, schema: MovimientoCreate) -> Movimiento:
        """Crea el nuevo registro. El commit lo maneja el Service."""
        db_obj = Movimiento(**schema.model_dump())
        self.db.add(db_obj)
        return db_obj