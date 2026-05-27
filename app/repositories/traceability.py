"""
Repositorio de Trazabilidad (Movimientos / Tipos / etc).

Sin commits internos: el servicio decide la atomicidad.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from app.core.errors import utcnow_naive
from sqlalchemy import and_, delete, desc, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.catalogs import Modelo, TipoActivo
from app.models.core import Activo
from app.models.location import Area
from app.models.organization import Persona
from app.models.traceability import (
    Evidencia,
    Mantenimiento,
    Movimiento,
    TipoEvidencia,
    TipoMantenimiento,
    TipoMovimiento,
)
from app.schemas.traceability import (
    MovimientoCreate,
    TipoMovimientoCreate,
    TipoMovimientoUpdate,
)


class TraceabilityRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # =====================================================================
    # TIPO MOVIMIENTO
    # =====================================================================
    async def create_tipo_movimiento(self, schema: TipoMovimientoCreate) -> TipoMovimiento:
        obj = TipoMovimiento(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_tipos_movimiento(self) -> List[TipoMovimiento]:
        result = await self.db.execute(select(TipoMovimiento))
        return result.scalars().all()

    async def get_tipo_by_id(self, id: int) -> Optional[TipoMovimiento]:
        result = await self.db.execute(
            select(TipoMovimiento).where(TipoMovimiento.TMO_Tipo_Movimiento == id)
        )
        return result.scalar_one_or_none()

    async def update_tipo(self, id: int, schema: TipoMovimientoUpdate) -> Optional[TipoMovimiento]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(TipoMovimiento)
                .where(TipoMovimiento.TMO_Tipo_Movimiento == id)
                .values(**data)
            )
            await self.db.flush()
        return await self.get_tipo_by_id(id)

    async def count_movimientos_by_tipo(self, tipo_id: int) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(Movimiento)
            .where(Movimiento.TMO_Tipo_Movimiento == tipo_id)
        )
        return result.scalar_one()

    async def delete_tipo(self, id: int):
        await self.db.execute(
            delete(TipoMovimiento).where(TipoMovimiento.TMO_Tipo_Movimiento == id)
        )

    # =====================================================================
    # MOVIMIENTOS
    # =====================================================================
    async def get_all_movimientos(self, skip: int = 0, limit: int = 50) -> List[Movimiento]:
        query = (
            select(Movimiento)
            .options(
                selectinload(Movimiento.persona),
                selectinload(Movimiento.tipo_movimiento),
                selectinload(Movimiento.area),
                selectinload(Movimiento.activo)
                .selectinload(Activo.modelo)
                .selectinload(Modelo.marca),
                selectinload(Movimiento.activo).selectinload(Activo.tipo_activo),
            )
            .order_by(desc(Movimiento.MOV_Fecha_Asignacion))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_movimiento_vigente(
        self, activo_id: uuid.UUID, *, lock: bool = False
    ) -> Optional[Movimiento]:
        """
        Devuelve el movimiento abierto del activo. Si `lock=True` y motor es
        Postgres, bloquea la fila para evitar race conditions.
        """
        query = select(Movimiento).where(
            and_(
                Movimiento.ACT_Activo == activo_id,
                Movimiento.MOV_Fecha_Devolucion.is_(None),
            )
        )
        if lock and not settings.IS_SQLITE:
            query = query.with_for_update()
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def cerrar_movimiento(self, movimiento_id: uuid.UUID) -> bool:
        """UPDATE condicional: solo cierra si está abierto. Retorna True si cerró 1 fila."""
        result = await self.db.execute(
            update(Movimiento)
            .where(
                Movimiento.MOV_Movimiento == movimiento_id,
                Movimiento.MOV_Fecha_Devolucion.is_(None),
            )
            .values(MOV_Fecha_Devolucion=utcnow_naive())
        )
        return result.rowcount == 1

    async def create_movimiento(self, schema: MovimientoCreate) -> Movimiento:
        obj = Movimiento(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    # Alias retro-compatible.
    create_movimiento_transactional = create_movimiento

    async def get_historial_activo(self, activo_id: uuid.UUID) -> List[Movimiento]:
        """Historial completo de movimientos de un activo (ordenado por fecha desc)."""
        from app.models.catalogs import Modelo

        query = (
            select(Movimiento)
            .options(
                selectinload(Movimiento.persona),
                selectinload(Movimiento.tipo_movimiento),
                selectinload(Movimiento.area),
            )
            .where(Movimiento.ACT_Activo == activo_id)
            .order_by(desc(Movimiento.MOV_Fecha_Asignacion))
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_asignaciones_vigentes_persona(
        self, persona_id: uuid.UUID
    ) -> List[Movimiento]:
        """Movimientos abiertos (sin devolución) asignados a una persona."""
        from app.models.catalogs import Modelo

        query = (
            select(Movimiento)
            .options(
                selectinload(Movimiento.persona),
                selectinload(Movimiento.tipo_movimiento),
                selectinload(Movimiento.area),
                selectinload(Movimiento.activo)
                .selectinload(Activo.modelo)
                .selectinload(Modelo.marca),
                selectinload(Movimiento.activo).selectinload(Activo.tipo_activo),
            )
            .where(
                Movimiento.PER_Persona == persona_id,
                Movimiento.MOV_Fecha_Devolucion.is_(None),
            )
            .order_by(desc(Movimiento.MOV_Fecha_Asignacion))
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def cerrar_todos_movimientos_persona(
        self, persona_id: uuid.UUID
    ) -> int:
        """
        Cierra TODOS los movimientos abiertos de una persona en un solo UPDATE.
        Retorna el número de movimientos cerrados.
        """
        result = await self.db.execute(
            update(Movimiento)
            .where(
                Movimiento.PER_Persona == persona_id,
                Movimiento.MOV_Fecha_Devolucion.is_(None),
            )
            .values(MOV_Fecha_Devolucion=utcnow_naive())
        )
        await self.db.flush()
        return result.rowcount

    async def get_by_id_full(self, id: uuid.UUID) -> Optional[Movimiento]:
        query = (
            select(Movimiento)
            .options(
                selectinload(Movimiento.persona),
                selectinload(Movimiento.area),
                selectinload(Movimiento.tipo_movimiento),
                selectinload(Movimiento.activo)
                .selectinload(Activo.modelo)
                .selectinload(Modelo.marca),
                selectinload(Movimiento.activo).selectinload(Activo.tipo_activo),
            )
            .where(Movimiento.MOV_Movimiento == id)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
