from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
from typing import List, Optional
import uuid

from app.models.software import TipoLicencia, Software, Licencia, Instalacion
from app.schemas.software import (
    TipoLicenciaCreate, SoftwareCreate, LicenciaCreate, InstalacionCreate
)

class SoftwareRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- CATALOGOS ---
    async def create_tipo_licencia(self, schema: TipoLicenciaCreate) -> TipoLicencia:
        db_obj = TipoLicencia(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_tipos_licencia(self) -> List[TipoLicencia]:
        result = await self.db.execute(select(TipoLicencia))
        return result.scalars().all()

    async def create_software(self, schema: SoftwareCreate) -> Software:
        db_obj = Software(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_software_all(self) -> List[Software]:
        result = await self.db.execute(select(Software))
        return result.scalars().all()

    # --- LICENCIAS ---
    async def create_licencia(self, schema: LicenciaCreate) -> Licencia:
        db_obj = Licencia(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_licencia_by_id(self, id: int) -> Optional[Licencia]:
        result = await self.db.execute(select(Licencia).where(Licencia.LIC_Licencia == id))
        return result.scalar_one_or_none()

    async def get_licencias_by_software(self, software_id: int) -> List[Licencia]:
        result = await self.db.execute(select(Licencia).where(Licencia.SOF_Software == software_id))
        return result.scalars().all()

    async def incrementar_uso_licencia(self, licencia_id: int):
        """Logica Atómica: Incrementa el contador de uso"""
        await self.db.execute(
            update(Licencia)
            .where(Licencia.LIC_Licencia == licencia_id)
            .values(LIC_Cantidad_Usada=Licencia.LIC_Cantidad_Usada + 1)
        )

 
    async def create_instalacion(self, schema: InstalacionCreate) -> Instalacion:
        db_obj = Instalacion(**schema.model_dump())
        self.db.add(db_obj)

        return db_obj

    async def get_instalacion_existente(self, activo_id: uuid.UUID, licencia_id: int) -> Optional[Instalacion]:
        """Verifica si ya está instalada para no duplicar"""
        query = select(Instalacion).where(
            Instalacion.ACT_Activo == activo_id,
            Instalacion.LIC_Licencia == licencia_id,
            Instalacion.INS_Estado == True
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    