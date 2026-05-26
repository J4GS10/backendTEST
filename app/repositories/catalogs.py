"""Repositorio de catálogos. Sin commits internos (servicio decide)."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.catalogs import (
    EstadoOperativo,
    Marca,
    Modelo,
    TipoActivo,
    TipoConexion,
    TipoEspecificacion,
)
from app.schemas.catalogs import (
    EstadoOperativoCreate,
    EstadoOperativoUpdate,
    MarcaCreate,
    MarcaUpdate,
    ModeloCreate,
    ModeloUpdate,
    TipoActivoCreate,
    TipoActivoUpdate,
    TipoConexionCreate,
    TipoConexionUpdate,
    TipoEspecificacionCreate,
    TipoEspecificacionUpdate,
)


class CatalogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # =====================================================================
    # TIPO DE ACTIVO
    # =====================================================================
    async def create_tipo_activo(self, schema: TipoActivoCreate) -> TipoActivo:
        obj = TipoActivo(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_tipos_activo(self) -> List[TipoActivo]:
        result = await self.db.execute(select(TipoActivo))
        return result.scalars().all()

    async def get_tipo_activo_by_name(self, name: str) -> Optional[TipoActivo]:
        result = await self.db.execute(select(TipoActivo).where(TipoActivo.TAC_Nombre == name))
        return result.scalar_one_or_none()

    async def get_tipo_activo_by_id(self, id: int) -> Optional[TipoActivo]:
        result = await self.db.execute(select(TipoActivo).where(TipoActivo.TAC_Tipo_Activo == id))
        return result.scalar_one_or_none()

    async def update_tipo_activo(self, id: int, schema: TipoActivoUpdate) -> Optional[TipoActivo]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(TipoActivo).where(TipoActivo.TAC_Tipo_Activo == id).values(**data)
            )
            await self.db.flush()
        return await self.get_tipo_activo_by_id(id)

    async def delete_tipo_activo(self, id: int) -> bool:
        result = await self.db.execute(
            delete(TipoActivo).where(TipoActivo.TAC_Tipo_Activo == id)
        )
        await self.db.flush()
        return result.rowcount > 0

    # =====================================================================
    # MARCA
    # =====================================================================
    async def create_marca(self, schema: MarcaCreate) -> Marca:
        obj = Marca(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_marcas(self) -> List[Marca]:
        result = await self.db.execute(select(Marca))
        return result.scalars().all()

    async def get_marca_by_name(self, name: str) -> Optional[Marca]:
        result = await self.db.execute(select(Marca).where(Marca.MAR_Nombre == name))
        return result.scalar_one_or_none()

    async def get_marca_by_id(self, id: int) -> Optional[Marca]:
        result = await self.db.execute(select(Marca).where(Marca.MAR_Marca == id))
        return result.scalar_one_or_none()

    async def update_marca(self, id: int, schema: MarcaUpdate) -> Optional[Marca]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(Marca).where(Marca.MAR_Marca == id).values(**data)
            )
            await self.db.flush()
        return await self.get_marca_by_id(id)

    async def delete_marca(self, id: int) -> bool:
        result = await self.db.execute(delete(Marca).where(Marca.MAR_Marca == id))
        await self.db.flush()
        return result.rowcount > 0

    # =====================================================================
    # TIPO DE CONEXIÓN
    # =====================================================================
    async def create_tipo_conexion(self, schema: TipoConexionCreate) -> TipoConexion:
        obj = TipoConexion(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_tipos_conexion(self) -> List[TipoConexion]:
        result = await self.db.execute(select(TipoConexion))
        return result.scalars().all()

    async def get_tipo_conexion_by_id(self, id: int) -> Optional[TipoConexion]:
        result = await self.db.execute(
            select(TipoConexion).where(TipoConexion.TCN_Tipo_Conexion == id)
        )
        return result.scalar_one_or_none()

    async def update_tipo_conexion(self, id: int, schema: TipoConexionUpdate) -> Optional[TipoConexion]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(TipoConexion)
                .where(TipoConexion.TCN_Tipo_Conexion == id)
                .values(**data)
            )
            await self.db.flush()
        return await self.get_tipo_conexion_by_id(id)

    async def delete_tipo_conexion(self, id: int) -> bool:
        result = await self.db.execute(
            delete(TipoConexion).where(TipoConexion.TCN_Tipo_Conexion == id)
        )
        await self.db.flush()
        return result.rowcount > 0

    # =====================================================================
    # MODELO
    # =====================================================================
    async def create_modelo(self, schema: ModeloCreate) -> Modelo:
        obj = Modelo(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_modelos_by_marca(self, marca_id: int) -> List[Modelo]:
        result = await self.db.execute(select(Modelo).where(Modelo.MAR_Marca == marca_id))
        return result.scalars().all()

    async def get_modelos_flat(self, q: str | None = None, limit: int = 500) -> list[dict]:
        """
        Devuelve modelos con marca embebida (plano) usando un único JOIN.
        Pensado para selects del frontend que necesitan ver "Marca + Modelo"
        sin hacer N requests (uno por marca).
        """
        from app.models.catalogs import Marca

        query = (
            select(
                Modelo.MOD_Modelo,
                Modelo.MOD_Nombre,
                Modelo.MAR_Marca,
                Marca.MAR_Nombre,
                Modelo.TCN_Tipo_Conexion,
                Modelo.MOD_Anio_Lanzamiento,
            )
            .join(Marca, Modelo.MAR_Marca == Marca.MAR_Marca)
            .order_by(Marca.MAR_Nombre.asc(), Modelo.MOD_Nombre.asc())
            .limit(limit)
        )
        if q:
            # Escape de wildcards LIKE para frenar patrones patológicos del usuario.
            safe_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{safe_q}%"
            query = query.where(
                (Modelo.MOD_Nombre.ilike(like, escape="\\"))
                | (Marca.MAR_Nombre.ilike(like, escape="\\"))
            )
        rows = (await self.db.execute(query)).all()
        return [
            {
                "MOD_Modelo": r[0],
                "MOD_Nombre": r[1],
                "MAR_Marca": r[2],
                "MAR_Nombre": r[3],
                "TCN_Tipo_Conexion": r[4],
                "MOD_Anio_Lanzamiento": r[5],
            }
            for r in rows
        ]

    async def get_modelo_by_id(self, id: int) -> Optional[Modelo]:
        result = await self.db.execute(select(Modelo).where(Modelo.MOD_Modelo == id))
        return result.scalar_one_or_none()

    async def update_modelo(self, id: int, schema: ModeloUpdate) -> Optional[Modelo]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(Modelo).where(Modelo.MOD_Modelo == id).values(**data)
            )
            await self.db.flush()
        return await self.get_modelo_by_id(id)

    async def delete_modelo(self, id: int) -> bool:
        result = await self.db.execute(delete(Modelo).where(Modelo.MOD_Modelo == id))
        await self.db.flush()
        return result.rowcount > 0

    # =====================================================================
    # ESTADO OPERATIVO
    # =====================================================================
    async def create_estado_operativo(self, schema: EstadoOperativoCreate) -> EstadoOperativo:
        obj = EstadoOperativo(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_estados_operativos(self) -> List[EstadoOperativo]:
        result = await self.db.execute(select(EstadoOperativo))
        return result.scalars().all()

    async def get_estado_operativo_by_id(self, id: int) -> Optional[EstadoOperativo]:
        result = await self.db.execute(
            select(EstadoOperativo).where(EstadoOperativo.EOP_Estado_Operativo == id)
        )
        return result.scalar_one_or_none()

    async def update_estado_operativo(self, id: int, schema: EstadoOperativoUpdate) -> Optional[EstadoOperativo]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(EstadoOperativo)
                .where(EstadoOperativo.EOP_Estado_Operativo == id)
                .values(**data)
            )
            await self.db.flush()
        return await self.get_estado_operativo_by_id(id)

    async def delete_estado_operativo(self, id: int) -> bool:
        result = await self.db.execute(
            delete(EstadoOperativo).where(EstadoOperativo.EOP_Estado_Operativo == id)
        )
        await self.db.flush()
        return result.rowcount > 0

    # =====================================================================
    # TIPO DE ESPECIFICACIÓN
    # =====================================================================
    async def create_tipo_especificacion(self, schema: TipoEspecificacionCreate) -> TipoEspecificacion:
        obj = TipoEspecificacion(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_tipos_especificacion(self) -> List[TipoEspecificacion]:
        result = await self.db.execute(select(TipoEspecificacion))
        return result.scalars().all()

    async def get_tipo_especificacion_by_id(self, id: int) -> Optional[TipoEspecificacion]:
        result = await self.db.execute(
            select(TipoEspecificacion).where(TipoEspecificacion.TES_Tipo_Especificacion == id)
        )
        return result.scalar_one_or_none()

    async def update_tipo_especificacion(self, id: int, schema: TipoEspecificacionUpdate) -> Optional[TipoEspecificacion]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(TipoEspecificacion)
                .where(TipoEspecificacion.TES_Tipo_Especificacion == id)
                .values(**data)
            )
            await self.db.flush()
        return await self.get_tipo_especificacion_by_id(id)

    async def delete_tipo_especificacion(self, id: int) -> bool:
        result = await self.db.execute(
            delete(TipoEspecificacion).where(TipoEspecificacion.TES_Tipo_Especificacion == id)
        )
        await self.db.flush()
        return result.rowcount > 0
