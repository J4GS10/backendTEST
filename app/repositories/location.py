from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional

from app.models.location import Pais, Estado, Municipio, Sede, Edificio, Nivel, Area
from app.schemas.location import (
    PaisCreate, EstadoCreate, MunicipioCreate, 
    SedeCreate, EdificioCreate, NivelCreate, AreaCreate
)

class LocationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- 1. PAIS ---
    async def create_pais(self, schema: PaisCreate) -> Pais:
        db_obj = Pais(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_paises(self) -> List[Pais]:
        result = await self.db.execute(select(Pais))
        return result.scalars().all()

    # --- 2. ESTADO ---
    async def create_estado(self, schema: EstadoCreate) -> Estado:
        db_obj = Estado(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_estados_by_pais(self, pais_id: int) -> List[Estado]:
        result = await self.db.execute(select(Estado).where(Estado.PAI_Pais == pais_id))
        return result.scalars().all()

    # --- 3. MUNICIPIO ---
    async def create_municipio(self, schema: MunicipioCreate) -> Municipio:
        db_obj = Municipio(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_municipios_by_estado(self, estado_id: int) -> List[Municipio]:
        result = await self.db.execute(select(Municipio).where(Municipio.EST_Estado == estado_id))
        return result.scalars().all()

    # --- 4. SEDE ---
    async def create_sede(self, schema: SedeCreate) -> Sede:
        db_obj = Sede(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_sedes_by_municipio(self, municipio_id: int) -> List[Sede]:
        result = await self.db.execute(select(Sede).where(Sede.MUN_Municipio == municipio_id))
        return result.scalars().all()

    # --- 5. EDIFICIO ---
    async def create_edificio(self, schema: EdificioCreate) -> Edificio:
        db_obj = Edificio(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_edificios_by_sede(self, sede_id: int) -> List[Edificio]:
        result = await self.db.execute(select(Edificio).where(Edificio.SED_Sede == sede_id))
        return result.scalars().all()

    # --- 6. NIVEL ---
    async def create_nivel(self, schema: NivelCreate) -> Nivel:
        db_obj = Nivel(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_niveles_by_edificio(self, edificio_id: int) -> List[Nivel]:
        result = await self.db.execute(select(Nivel).where(Nivel.EDI_Edificio == edificio_id))
        return result.scalars().all()

    # --- 7. AREA ---
    async def create_area(self, schema: AreaCreate) -> Area:
        db_obj = Area(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_areas_by_nivel(self, nivel_id: int) -> List[Area]:
        result = await self.db.execute(select(Area).where(Area.NIV_Nivel == nivel_id))
        return result.scalars().all()
    
    async def get_area_by_id(self, id: int) -> Optional[Area]:
        result = await self.db.execute(select(Area).where(Area.ARE_Area == id))
        return result.scalar_one_or_none()