"""
Repositorio de Software/Licencias/Instalaciones.

Reglas de transacción:
- Los repos NO commitean. Solo hacen `flush()` cuando necesitan que se asigne PK.
- El servicio es responsable del commit/rollback al final del flujo.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.software import Instalacion, Licencia, Software, TipoLicencia
from app.schemas.software import (
    InstalacionCreate,
    LicenciaCreate,
    LicenciaUpdate,
    SoftwareCreate,
    SoftwareUpdate,
    TipoLicenciaCreate,
    TipoLicenciaUpdate,
)


class SoftwareRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # =====================================================================
    # TIPO LICENCIA
    # =====================================================================
    async def create_tipo_licencia(self, schema: TipoLicenciaCreate) -> TipoLicencia:
        obj = TipoLicencia(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_tipos_licencia(self) -> List[TipoLicencia]:
        result = await self.db.execute(select(TipoLicencia))
        return result.scalars().all()

    async def get_tipo_licencia_by_id(self, id: int) -> Optional[TipoLicencia]:
        result = await self.db.execute(
            select(TipoLicencia).where(TipoLicencia.TLI_Tipo_Licencia == id)
        )
        return result.scalar_one_or_none()

    async def update_tipo_licencia(self, id: int, schema: TipoLicenciaUpdate) -> Optional[TipoLicencia]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(TipoLicencia)
                .where(TipoLicencia.TLI_Tipo_Licencia == id)
                .values(**data)
            )
            await self.db.flush()
        return await self.get_tipo_licencia_by_id(id)

    async def count_licencias_by_tipo(self, tipo_id: int) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(Licencia).where(Licencia.TLI_Tipo_Licencia == tipo_id)
        )
        return result.scalar_one()

    async def delete_tipo_licencia(self, id: int):
        await self.db.execute(
            delete(TipoLicencia).where(TipoLicencia.TLI_Tipo_Licencia == id)
        )

    # =====================================================================
    # SOFTWARE
    # =====================================================================
    async def create_software(self, schema: SoftwareCreate) -> Software:
        obj = Software(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_software_all(self) -> List[Software]:
        result = await self.db.execute(select(Software))
        return result.scalars().all()

    async def get_software_by_id(self, id: int) -> Optional[Software]:
        result = await self.db.execute(select(Software).where(Software.SOF_Software == id))
        return result.scalar_one_or_none()

    async def update_software(self, id: int, schema: SoftwareUpdate) -> Optional[Software]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(Software).where(Software.SOF_Software == id).values(**data)
            )
            await self.db.flush()
        return await self.get_software_by_id(id)

    async def count_licencias_by_software(self, software_id: int) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(Licencia).where(Licencia.SOF_Software == software_id)
        )
        return result.scalar_one()

    async def delete_software(self, id: int):
        await self.db.execute(delete(Software).where(Software.SOF_Software == id))

    # =====================================================================
    # LICENCIAS
    # =====================================================================
    async def create_licencia(self, schema: LicenciaCreate) -> Licencia:
        obj = Licencia(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_licencia_by_id(self, id: int) -> Optional[Licencia]:
        result = await self.db.execute(select(Licencia).where(Licencia.LIC_Licencia == id))
        return result.scalar_one_or_none()

    async def get_licencias_by_software(self, software_id: int) -> List[Licencia]:
        result = await self.db.execute(
            select(Licencia).where(Licencia.SOF_Software == software_id)
        )
        return result.scalars().all()

    async def update_licencia(self, id: int, schema: LicenciaUpdate) -> Optional[Licencia]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(Licencia).where(Licencia.LIC_Licencia == id).values(**data)
            )
            await self.db.flush()
        return await self.get_licencia_by_id(id)

    async def delete_licencia(self, id: int):
        await self.db.execute(delete(Licencia).where(Licencia.LIC_Licencia == id))
        await self.db.flush()

    async def count_instalaciones_activas_de_licencia(self, id: int) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(Instalacion)
            .where(Instalacion.LIC_Licencia == id, Instalacion.INS_Estado.is_(True))
        )
        return result.scalar_one()

    async def reservar_cupo_licencia(self, licencia_id: int) -> bool:
        """
        UPDATE condicional ATÓMICO: incrementa LIC_Cantidad_Usada solo si
        aún hay cupos disponibles. Retorna True si reservó, False si no.

        Esto elimina la race condition clásica del patrón "read-then-write".
        """
        result = await self.db.execute(
            update(Licencia)
            .where(
                Licencia.LIC_Licencia == licencia_id,
                Licencia.LIC_Cantidad_Usada < Licencia.LIC_Cantidad_Total,
            )
            .values(LIC_Cantidad_Usada=Licencia.LIC_Cantidad_Usada + 1)
        )
        return result.rowcount == 1

    async def liberar_cupo_licencia(self, licencia_id: int) -> bool:
        """UPDATE condicional: decrementa solo si > 0 (nunca por debajo de cero)."""
        result = await self.db.execute(
            update(Licencia)
            .where(
                Licencia.LIC_Licencia == licencia_id,
                Licencia.LIC_Cantidad_Usada > 0,
            )
            .values(LIC_Cantidad_Usada=Licencia.LIC_Cantidad_Usada - 1)
        )
        return result.rowcount == 1

    # =====================================================================
    # INSTALACIONES
    # =====================================================================
    async def create_instalacion(self, schema: InstalacionCreate) -> Instalacion:
        obj = Instalacion(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_instalaciones_by_activo(
        self, activo_id: uuid.UUID, solo_activas: bool = True
    ) -> List[Instalacion]:
        """Lista todas las instalaciones de un activo (opcional: solo las activas)."""
        from sqlalchemy.orm import selectinload
        query = (
            select(Instalacion)
            .options(
                selectinload(Instalacion.licencia).selectinload(Licencia.software),
                selectinload(Instalacion.licencia).selectinload(Licencia.tipo_licencia),
            )
            .where(Instalacion.ACT_Activo == activo_id)
        )
        if solo_activas:
            query = query.where(Instalacion.INS_Estado.is_(True))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_instalacion_activa(
        self, activo_id: uuid.UUID, licencia_id: int
    ) -> Optional[Instalacion]:
        query = select(Instalacion).where(
            Instalacion.ACT_Activo == activo_id,
            Instalacion.LIC_Licencia == licencia_id,
            Instalacion.INS_Estado.is_(True),
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def desactivar_instalacion_atomico(
        self, activo_id: uuid.UUID, licencia_id: int
    ) -> bool:
        """
        UPDATE condicional: solo desactiva si está activa. Retorna True si
        cambió 1 fila. Esto previene doble-desinstalación que decrementa
        el contador dos veces.
        """
        result = await self.db.execute(
            update(Instalacion)
            .where(
                Instalacion.ACT_Activo == activo_id,
                Instalacion.LIC_Licencia == licencia_id,
                Instalacion.INS_Estado.is_(True),
            )
            .values(INS_Estado=False)
        )
        return result.rowcount == 1
