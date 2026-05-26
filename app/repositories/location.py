from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, delete, func
from typing import List, Optional

from app.models.location import Pais, Estado, Municipio, Sede, Edificio, Nivel, Area
from app.schemas.location import (
    PaisCreate, PaisUpdate,
    EstadoCreate, EstadoUpdate,
    MunicipioCreate, MunicipioUpdate,
    SedeCreate, SedeUpdate,
    EdificioCreate, EdificioUpdate,
    NivelCreate, NivelUpdate,
    AreaCreate, AreaUpdate
)


class LocationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # =================================================================
    # GENERIC HELPERS (para reducir repetición)
    # =================================================================
    async def _get_by_pk(self, model, pk_col, pk_val):
        result = await self.db.execute(select(model).where(pk_col == pk_val))
        return result.scalar_one_or_none()

    async def _count_children(self, child_model, fk_col, parent_id: int) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(child_model).where(fk_col == parent_id)
        )
        return result.scalar_one()

    async def _update_entity(self, model, pk_col, pk_val: int, schema):
        update_data = schema.model_dump(exclude_unset=True)
        if update_data:
            query = update(model).where(pk_col == pk_val).values(**update_data)
            await self.db.execute(query)
            await self.db.flush()
        return await self._get_by_pk(model, pk_col, pk_val)

    async def _delete_entity(self, model, pk_col, pk_val: int):
        query = delete(model).where(pk_col == pk_val)
        await self.db.execute(query)
        await self.db.flush()

    # =================================================================
    # 1. PAIS
    # =================================================================
    async def create_pais(self, schema: PaisCreate) -> Pais:
        db_obj = Pais(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.flush()
        return db_obj

    async def get_paises(self) -> List[Pais]:
        result = await self.db.execute(select(Pais))
        return result.scalars().all()

    async def get_pais_by_id(self, id: int) -> Optional[Pais]:
        return await self._get_by_pk(Pais, Pais.PAI_Pais, id)

    async def update_pais(self, id: int, schema: PaisUpdate):
        return await self._update_entity(Pais, Pais.PAI_Pais, id, schema)

    async def delete_pais(self, id: int):
        await self._delete_entity(Pais, Pais.PAI_Pais, id)

    async def count_estados_by_pais(self, pais_id: int) -> int:
        return await self._count_children(Estado, Estado.PAI_Pais, pais_id)

    # =================================================================
    # 2. ESTADO
    # =================================================================
    async def create_estado(self, schema: EstadoCreate) -> Estado:
        db_obj = Estado(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.flush()
        return db_obj

    async def get_estados_by_pais(self, pais_id: int) -> List[Estado]:
        result = await self.db.execute(select(Estado).where(Estado.PAI_Pais == pais_id))
        return result.scalars().all()

    async def get_estado_by_id(self, id: int) -> Optional[Estado]:
        return await self._get_by_pk(Estado, Estado.EST_Estado, id)

    async def update_estado(self, id: int, schema: EstadoUpdate):
        return await self._update_entity(Estado, Estado.EST_Estado, id, schema)

    async def delete_estado(self, id: int):
        await self._delete_entity(Estado, Estado.EST_Estado, id)

    async def count_municipios_by_estado(self, estado_id: int) -> int:
        return await self._count_children(Municipio, Municipio.EST_Estado, estado_id)

    # =================================================================
    # 3. MUNICIPIO
    # =================================================================
    async def create_municipio(self, schema: MunicipioCreate) -> Municipio:
        db_obj = Municipio(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.flush()
        return db_obj

    async def get_municipios_by_estado(self, estado_id: int) -> List[Municipio]:
        result = await self.db.execute(select(Municipio).where(Municipio.EST_Estado == estado_id))
        return result.scalars().all()

    async def get_municipio_by_id(self, id: int) -> Optional[Municipio]:
        return await self._get_by_pk(Municipio, Municipio.MUN_Municipio, id)

    async def update_municipio(self, id: int, schema: MunicipioUpdate):
        return await self._update_entity(Municipio, Municipio.MUN_Municipio, id, schema)

    async def delete_municipio(self, id: int):
        await self._delete_entity(Municipio, Municipio.MUN_Municipio, id)

    async def count_sedes_by_municipio(self, municipio_id: int) -> int:
        return await self._count_children(Sede, Sede.MUN_Municipio, municipio_id)

    # =================================================================
    # 4. SEDE
    # =================================================================
    async def create_sede(self, schema: SedeCreate) -> Sede:
        db_obj = Sede(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.flush()
        return db_obj

    async def get_sedes_by_municipio(self, municipio_id: int) -> List[Sede]:
        result = await self.db.execute(select(Sede).where(Sede.MUN_Municipio == municipio_id))
        return result.scalars().all()

    async def get_sede_by_id(self, id: int) -> Optional[Sede]:
        return await self._get_by_pk(Sede, Sede.SED_Sede, id)

    async def update_sede(self, id: int, schema: SedeUpdate):
        return await self._update_entity(Sede, Sede.SED_Sede, id, schema)

    async def delete_sede(self, id: int):
        await self._delete_entity(Sede, Sede.SED_Sede, id)

    async def count_edificios_by_sede(self, sede_id: int) -> int:
        return await self._count_children(Edificio, Edificio.SED_Sede, sede_id)

    # =================================================================
    # 5. EDIFICIO
    # =================================================================
    async def create_edificio(self, schema: EdificioCreate) -> Edificio:
        db_obj = Edificio(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.flush()
        return db_obj

    async def get_edificios_by_sede(self, sede_id: int) -> List[Edificio]:
        result = await self.db.execute(select(Edificio).where(Edificio.SED_Sede == sede_id))
        return result.scalars().all()

    async def get_edificio_by_id(self, id: int) -> Optional[Edificio]:
        return await self._get_by_pk(Edificio, Edificio.EDI_Edificio, id)

    async def update_edificio(self, id: int, schema: EdificioUpdate):
        return await self._update_entity(Edificio, Edificio.EDI_Edificio, id, schema)

    async def delete_edificio(self, id: int):
        await self._delete_entity(Edificio, Edificio.EDI_Edificio, id)

    async def count_niveles_by_edificio(self, edificio_id: int) -> int:
        return await self._count_children(Nivel, Nivel.EDI_Edificio, edificio_id)

    # =================================================================
    # 6. NIVEL
    # =================================================================
    async def create_nivel(self, schema: NivelCreate) -> Nivel:
        db_obj = Nivel(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.flush()
        return db_obj

    async def get_niveles_by_edificio(self, edificio_id: int) -> List[Nivel]:
        result = await self.db.execute(select(Nivel).where(Nivel.EDI_Edificio == edificio_id))
        return result.scalars().all()

    async def get_nivel_by_id(self, id: int) -> Optional[Nivel]:
        return await self._get_by_pk(Nivel, Nivel.NIV_Nivel, id)

    async def update_nivel(self, id: int, schema: NivelUpdate):
        return await self._update_entity(Nivel, Nivel.NIV_Nivel, id, schema)

    async def delete_nivel(self, id: int):
        await self._delete_entity(Nivel, Nivel.NIV_Nivel, id)

    async def count_areas_by_nivel(self, nivel_id: int) -> int:
        return await self._count_children(Area, Area.NIV_Nivel, nivel_id)

    # =================================================================
    # 7. AREA
    # =================================================================
    async def create_area(self, schema: AreaCreate) -> Area:
        db_obj = Area(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.flush()
        return db_obj

    async def get_areas_by_nivel(self, nivel_id: int) -> List[Area]:
        result = await self.db.execute(select(Area).where(Area.NIV_Nivel == nivel_id))
        return result.scalars().all()

    async def get_area_by_id(self, id: int) -> Optional[Area]:
        return await self._get_by_pk(Area, Area.ARE_Area, id)

    async def update_area(self, id: int, schema: AreaUpdate):
        return await self._update_entity(Area, Area.ARE_Area, id, schema)

    async def delete_area(self, id: int):
        await self._delete_entity(Area, Area.ARE_Area, id)