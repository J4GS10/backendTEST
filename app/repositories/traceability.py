from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, and_, desc
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime
import uuid

# --- MODELOS ---
# Mantenemos TODOS los modelos de Producción para garantizar integridad referencial
# y evitar errores si estos modelos son usados por lógica extendida no visible aquí.
from app.models.traceability import (
    Movimiento, TipoMovimiento,
    Mantenimiento, TipoMantenimiento,
    Evidencia, TipoEvidencia
)

# Modelos Relacionados
from app.models.core import Activo
from app.models.catalogs import Modelo, Marca, TipoActivo
from app.models.organization import Persona
from app.models.location import Area

# Schemas
from app.schemas.traceability import MovimientoCreate, TipoMovimientoCreate


class TraceabilityRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ==========================================================================
    #                                TIPOS
    # ==========================================================================
    async def create_tipo_movimiento(self, schema: TipoMovimientoCreate) -> TipoMovimiento:
        db_obj = TipoMovimiento(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_tipos_movimiento(self) -> List[TipoMovimiento]:
        result = await self.db.execute(select(TipoMovimiento))
        return result.scalars().all()

    # ==========================================================================
    #                             MOVIMIENTOS
    # ==========================================================================

    async def get_all_movimientos(self) -> List[Movimiento]:
        """
        Obtiene historial con todas las relaciones cargadas.
        
        DECISIÓN DE ARQUITECTURA:
        Se mantiene la carga profunda (Marca, TipoActivo) de Producción.
        Reducir esto (como sugería el código a implementar) causaría que la tabla
        del frontend muestre datos vacíos.
        """
        query = (
            select(Movimiento)
            .options(
                # Cargas directas (Evita MissingGreenlet en Pydantic)
                selectinload(Movimiento.persona),
                selectinload(Movimiento.tipo_movimiento),
                selectinload(Movimiento.area),

                # Carga profunda del Activo
                selectinload(Movimiento.activo)
                .selectinload(Activo.modelo)
                .selectinload(Modelo.marca),

                selectinload(Movimiento.activo)
                .selectinload(Activo.tipo_activo)
            )
            .order_by(desc(Movimiento.MOV_Fecha_Asignacion))
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_movimiento_vigente(self, activo_id: uuid.UUID) -> Optional[Movimiento]:
        """
        Busca si el activo tiene una asignación abierta (MOV_Fecha_Devolucion is NULL)
        """
        query = select(Movimiento).where(
            and_(
                Movimiento.ACT_Activo == activo_id,
                Movimiento.MOV_Fecha_Devolucion == None
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def cerrar_movimiento(self, movimiento_id: uuid.UUID):
        """
        Cierra el ciclo de custodia anterior (actualiza MOV_Fecha_Devolucion).
        NOTA: el commit lo manejas desde el Service.
        """
        query = (
            update(Movimiento)
            .where(Movimiento.MOV_Movimiento == movimiento_id)
            .values(MOV_Fecha_Devolucion=datetime.now())
        )
        await self.db.execute(query)

    async def create_movimiento_transactional(self, schema: MovimientoCreate) -> Movimiento:
        """
        Crea el nuevo registro. El commit lo maneja el Service para garantizar atomicidad.
        """
        db_obj = Movimiento(**schema.model_dump())
        self.db.add(db_obj)
        return db_obj

    async def get_by_id_full(self, id: uuid.UUID) -> Optional[Movimiento]:
        """
        Obtiene el movimiento con carga profunda (Eager Loading).
        Esencial para:
        1. Generación de Actas de Entrega (PDF).
        2. Respuesta completa de la API tras la creación.
        """
        query = (
            select(Movimiento)
            .options(
                # 1. Relaciones directas (Solicitadas en Implementación)
                selectinload(Movimiento.persona),
                selectinload(Movimiento.area),
                selectinload(Movimiento.tipo_movimiento),

                # 2. Relaciones profundas del Activo (Solicitadas en Producción)
                # Activo -> Modelo -> Marca
                selectinload(Movimiento.activo)
                .selectinload(Activo.modelo)
                .selectinload(Modelo.marca),

                # Activo -> TipoActivo
                selectinload(Movimiento.activo)
                .selectinload(Activo.tipo_activo)
            )
            .where(Movimiento.MOV_Movimiento == id)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()