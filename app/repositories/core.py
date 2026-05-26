from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import update, func
from typing import List, Optional
import uuid

from app.models.core import Activo, Especificacion
from app.models.catalogs import Modelo, Marca, TipoActivo, EstadoOperativo
from app.schemas.core import ActivoCreate, EspecificacionCreate, ActivoUpdate, ActivoFilter


class CoreRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_codigo_interno(self, codigo: str) -> Optional[Activo]:
        result = await self.db.execute(select(Activo).where(Activo.ACT_Codigo_Interno == codigo))
        return result.scalar_one_or_none()

    async def get_by_serie(self, serie: str) -> Optional[Activo]:
        result = await self.db.execute(select(Activo).where(Activo.ACT_Serie_Fabricante == serie))
        return result.scalar_one_or_none()
    
    async def get_by_id(self, id: uuid.UUID) -> Optional[Activo]:
        query = (
            select(Activo)
            .options(
                selectinload(Activo.especificaciones),
                selectinload(Activo.modelo).selectinload(Modelo.marca),
                selectinload(Activo.tipo_activo),
                selectinload(Activo.estado_operativo)
            )
            .where(Activo.ACT_Activo == id)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_id_simple(self, id: uuid.UUID) -> Optional[Activo]:
        """Consulta ligera sin todas las relaciones, para validaciones internas"""
        result = await self.db.execute(select(Activo).where(Activo.ACT_Activo == id))
        return result.scalar_one_or_none()


    async def create_activo(self, schema: ActivoCreate) -> Activo:
        """Crea activo + especificaciones. No commitea (servicio decide)."""
        activo_data = schema.model_dump(exclude={"especificaciones"})
        db_activo = Activo(**activo_data)
        self.db.add(db_activo)

        if schema.especificaciones:
            for spec_schema in schema.especificaciones:
                db_spec = Especificacion(
                    **spec_schema.model_dump(),
                    activo=db_activo,
                )
                self.db.add(db_spec)

        await self.db.flush()

        query = (
            select(Activo)
            .options(selectinload(Activo.especificaciones))
            .where(Activo.ACT_Activo == db_activo.ACT_Activo)
        )
        result = await self.db.execute(query)
        return result.scalar_one()

    async def update_activo(self, id: uuid.UUID, schema: ActivoUpdate) -> Activo:
        """Actualiza activo. No commitea (servicio decide)."""
        update_data = schema.model_dump(exclude_unset=True)
        if not update_data:
            return await self.get_by_id(id)

        await self.db.execute(
            update(Activo).where(Activo.ACT_Activo == id).values(**update_data)
        )
        await self.db.flush()
        return await self.get_by_id(id)

    async def get_all(self, skip: int = 0, limit: int = 100) -> List[Activo]:
        query = select(Activo).options(selectinload(Activo.especificaciones)).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def count_activos(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(Activo))
        return result.scalar() or 0

    async def count_activos_by_estado(self, estado_id: int) -> int:
        result = await self.db.execute(select(func.count()).select_from(Activo).where(Activo.EOP_Estado_Operativo == estado_id))
        return result.scalar() or 0

    async def search_activos(self, filters: ActivoFilter) -> tuple[List[Activo], int]:
        """
        Retorna (lista_activos, total_count) aplicando filtros dinámicos.
        """
        query = select(Activo).options(
            selectinload(Activo.especificaciones),
            selectinload(Activo.modelo).selectinload(Modelo.marca),
            selectinload(Activo.tipo_activo),
            selectinload(Activo.estado_operativo),
        )

        # Construcción dinámica de filtros
        conditions = []
        
        if filters.q:
            # Escape de wildcards LIKE para que el usuario no construya patrones
            # patológicos (`%_%_%_...`) ni metacaracteres. ilike usa `\\` como
            # escape por defecto en PostgreSQL.
            safe_q = filters.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            search_term = f"%{safe_q}%"
            conditions.append(
                (Activo.ACT_Codigo_Interno.ilike(search_term, escape="\\")) |
                (Activo.ACT_Hostname.ilike(search_term, escape="\\")) |
                (Activo.ACT_Serie_Fabricante.ilike(search_term, escape="\\"))
            )
        
        if filters.modelo_id:
            conditions.append(Activo.MOD_Modelo == filters.modelo_id)
        
        if filters.tipo_activo_id:
            conditions.append(Activo.TAC_Tipo_Activo == filters.tipo_activo_id)
            
        if filters.estado_operativo_id:
            conditions.append(Activo.EOP_Estado_Operativo == filters.estado_operativo_id)

        if filters.fecha_compra_start:
            conditions.append(Activo.ACT_Fecha_Compra >= filters.fecha_compra_start)
            
        if filters.fecha_compra_end:
            conditions.append(Activo.ACT_Fecha_Compra <= filters.fecha_compra_end)

        if conditions:
            query = query.where(*conditions)

        # Contar total (antes de paginar)
        # Nota: Para optimización extrema en tablas gigantes, count(*) over() o query separada
        count_query = select(func.count()).select_from(Activo)
        if conditions:
            count_query = count_query.where(*conditions)
            
        total = (await self.db.execute(count_query)).scalar() or 0

        # Paginación
        skip = (filters.page - 1) * filters.per_page
        query = query.offset(skip).limit(filters.per_page)
        
        # Ordenamiento default: Recientes primero
        query = query.order_by(Activo.ACT_Fecha_Compra.desc())

        result = await self.db.execute(query)
        return result.scalars().all(), total
