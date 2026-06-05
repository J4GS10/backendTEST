"""Repositorio de Adjuntos. Sin commits internos: solo flush()."""
from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.attachment import Adjunto


class AttachmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, adjunto: Adjunto) -> Adjunto:
        self.db.add(adjunto)
        await self.db.flush()
        return adjunto

    async def get_by_id(self, id: uuid.UUID) -> Optional[Adjunto]:
        result = await self.db.execute(select(Adjunto).where(Adjunto.ADJ_Adjunto == id))
        return result.scalar_one_or_none()

    async def get_by_activo(self, activo_id: uuid.UUID) -> List[Adjunto]:
        result = await self.db.execute(
            select(Adjunto)
            .where(Adjunto.ACT_Activo == activo_id)
            .order_by(Adjunto.ADJ_Fecha_Subida.desc())
        )
        return result.scalars().all()

    async def get_by_orden(self, orden_id: int) -> List[Adjunto]:
        result = await self.db.execute(
            select(Adjunto)
            .where(Adjunto.OCO_Orden == orden_id)
            .order_by(Adjunto.ADJ_Fecha_Subida.desc())
        )
        return result.scalars().all()

    async def delete(self, id: uuid.UUID) -> None:
        await self.db.execute(delete(Adjunto).where(Adjunto.ADJ_Adjunto == id))
        await self.db.flush()
