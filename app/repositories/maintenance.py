"""Repositorio de mantenimientos. Flush-only (service decide commit)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, desc, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.models.core import Activo
from app.models.traceability import DetalleMantenimiento, Mantenimiento, TipoMantenimiento
from app.schemas.maintenance import (
    DetalleCreate,
    MantenimientoCreate,
    TipoMantenimientoCreate,
    TipoMantenimientoUpdate,
)


class MaintenanceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # =====================================================================
    # TIPOS
    # =====================================================================
    async def create_tipo(self, schema: TipoMantenimientoCreate) -> TipoMantenimiento:
        obj = TipoMantenimiento(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_tipos(self) -> List[TipoMantenimiento]:
        result = await self.db.execute(select(TipoMantenimiento))
        return result.scalars().all()

    async def get_tipo_by_id(self, id: int) -> Optional[TipoMantenimiento]:
        result = await self.db.execute(
            select(TipoMantenimiento).where(TipoMantenimiento.TMA_Tipo_Mantenimiento == id)
        )
        return result.scalar_one_or_none()

    async def update_tipo(self, id: int, schema: TipoMantenimientoUpdate) -> Optional[TipoMantenimiento]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(TipoMantenimiento)
                .where(TipoMantenimiento.TMA_Tipo_Mantenimiento == id)
                .values(**data)
            )
            await self.db.flush()
        return await self.get_tipo_by_id(id)

    async def count_mantenimientos_by_tipo(self, tipo_id: int) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(Mantenimiento)
            .where(Mantenimiento.TMA_Tipo_Mantenimiento == tipo_id)
        )
        return result.scalar_one()

    async def delete_tipo(self, id: int):
        await self.db.execute(
            delete(TipoMantenimiento).where(TipoMantenimiento.TMA_Tipo_Mantenimiento == id)
        )
        await self.db.flush()

    # =====================================================================
    # MANTENIMIENTOS
    # =====================================================================
    async def create_mantenimiento(self, schema: MantenimientoCreate) -> Mantenimiento:
        data = schema.model_dump(exclude={"detalles"})
        obj = Mantenimiento(**data)
        self.db.add(obj)

        for det in schema.detalles or []:
            d = DetalleMantenimiento(**det.model_dump(), mantenimiento=obj)
            self.db.add(d)

        await self.db.flush()
        return await self.get_by_id(obj.MAN_Mantenimiento)

    async def get_all(self, skip: int = 0, limit: int = 50) -> List[Mantenimiento]:
        query = (
            select(Mantenimiento)
            .options(
                selectinload(Mantenimiento.tipo_mantenimiento),
                selectinload(Mantenimiento.activo).selectinload(Activo.modelo),
                selectinload(Mantenimiento.persona_solicita),
                selectinload(Mantenimiento.detalles),
            )
            .order_by(desc(Mantenimiento.MAN_Fecha_Ingreso))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_by_id(self, id: uuid.UUID) -> Optional[Mantenimiento]:
        query = (
            select(Mantenimiento)
            .options(
                selectinload(Mantenimiento.tipo_mantenimiento),
                selectinload(Mantenimiento.activo),
                selectinload(Mantenimiento.persona_solicita),
                selectinload(Mantenimiento.detalles),
            )
            .where(Mantenimiento.MAN_Mantenimiento == id)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def add_detalle(self, mantenimiento_id: uuid.UUID, schema: DetalleCreate) -> DetalleMantenimiento:
        obj = DetalleMantenimiento(**schema.model_dump(), MAN_Mantenimiento=mantenimiento_id)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_detalle_by_id(self, detalle_id: int) -> Optional[DetalleMantenimiento]:
        result = await self.db.execute(
            select(DetalleMantenimiento).where(DetalleMantenimiento.DMA_Detalle_Mant == detalle_id)
        )
        return result.scalar_one_or_none()

    async def list_detalles(self, mantenimiento_id: uuid.UUID) -> List[DetalleMantenimiento]:
        result = await self.db.execute(
            select(DetalleMantenimiento).where(
                DetalleMantenimiento.MAN_Mantenimiento == mantenimiento_id
            )
        )
        return result.scalars().all()

    async def update_detalle(self, detalle_id: int, schema: DetalleCreate) -> Optional[DetalleMantenimiento]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(DetalleMantenimiento)
                .where(DetalleMantenimiento.DMA_Detalle_Mant == detalle_id)
                .values(**data)
            )
            await self.db.flush()
        return await self.get_detalle_by_id(detalle_id)

    async def delete_detalle(self, detalle_id: int):
        await self.db.execute(
            delete(DetalleMantenimiento).where(DetalleMantenimiento.DMA_Detalle_Mant == detalle_id)
        )
        await self.db.flush()

    async def close_mantenimiento(
        self, mantenimiento_id: uuid.UUID, fecha_cierre: datetime, costo_total
    ):
        await self.db.execute(
            update(Mantenimiento)
            .where(Mantenimiento.MAN_Mantenimiento == mantenimiento_id)
            .values(MAN_Fecha_Cierre=fecha_cierre, MAN_Costo_Total=costo_total)
        )
        await self.db.flush()
        return await self.get_by_id(mantenimiento_id)

    async def delete_mantenimiento(self, mantenimiento_id: uuid.UUID):
        await self.db.execute(
            delete(Mantenimiento).where(Mantenimiento.MAN_Mantenimiento == mantenimiento_id)
        )
        await self.db.flush()
