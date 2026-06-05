"""
Repositorio de Consumibles. Sin commits internos: solo flush(). El servicio
decide la atomicidad.

El decremento de stock (SALIDA) usa un UPDATE condicional atómico —mismo patrón
que la reserva de cupos de licencia— para eliminar la race condition clásica
read-then-write y garantizar que el stock nunca quede negativo.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.consumable import Consumible, MovimientoConsumible
from app.schemas.consumable import ConsumibleCreate, ConsumibleUpdate


class ConsumibleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, schema: ConsumibleCreate) -> Consumible:
        obj = Consumible(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_all(self, solo_bajo_stock: bool = False) -> List[Consumible]:
        query = select(Consumible).order_by(Consumible.CON_Nombre)
        if solo_bajo_stock:
            query = query.where(
                Consumible.CON_Stock_Minimo > 0,
                Consumible.CON_Stock_Actual <= Consumible.CON_Stock_Minimo,
            )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_by_id(self, id: int) -> Optional[Consumible]:
        result = await self.db.execute(
            select(Consumible).where(Consumible.CON_Consumible == id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, nombre: str) -> Optional[Consumible]:
        result = await self.db.execute(
            select(Consumible).where(Consumible.CON_Nombre == nombre)
        )
        return result.scalar_one_or_none()

    async def update(self, id: int, schema: ConsumibleUpdate) -> Optional[Consumible]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(Consumible).where(Consumible.CON_Consumible == id).values(**data)
            )
            await self.db.flush()
        return await self.get_by_id(id)

    async def delete(self, id: int) -> None:
        await self.db.execute(delete(Consumible).where(Consumible.CON_Consumible == id))
        await self.db.flush()

    async def count_movimientos(self, id: int) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(MovimientoConsumible)
            .where(MovimientoConsumible.CON_Consumible == id)
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Stock — operaciones atómicas
    # ------------------------------------------------------------------
    async def incrementar_stock(self, id: int, cantidad: int) -> bool:
        """ENTRADA: suma stock. Retorna True si la fila existe y se actualizó."""
        result = await self.db.execute(
            update(Consumible)
            .where(Consumible.CON_Consumible == id)
            .values(CON_Stock_Actual=Consumible.CON_Stock_Actual + cantidad)
        )
        return result.rowcount == 1

    async def decrementar_stock(self, id: int, cantidad: int) -> bool:
        """
        SALIDA: resta stock SOLO si hay suficiente (UPDATE condicional atómico).
        Retorna False si no existe o no hay stock suficiente — sin race condition.
        """
        result = await self.db.execute(
            update(Consumible)
            .where(
                Consumible.CON_Consumible == id,
                Consumible.CON_Stock_Actual >= cantidad,
            )
            .values(CON_Stock_Actual=Consumible.CON_Stock_Actual - cantidad)
        )
        return result.rowcount == 1

    async def add_movimiento(self, mov: MovimientoConsumible) -> MovimientoConsumible:
        self.db.add(mov)
        await self.db.flush()
        return mov

    async def get_movimientos(self, consumible_id: int) -> List[MovimientoConsumible]:
        result = await self.db.execute(
            select(MovimientoConsumible)
            .where(MovimientoConsumible.CON_Consumible == consumible_id)
            .order_by(MovimientoConsumible.MOC_Fecha.desc())
        )
        return result.scalars().all()
