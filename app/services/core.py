from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import uuid

from app.repositories.core import CoreRepository
from app.repositories.catalogs import CatalogRepository
from app.repositories.governance import GovernanceRepository
from app.repositories.traceability import TraceabilityRepository

from app.models.location import Area
from app.models.organization import Persona
from app.models.traceability import TipoMovimiento

from app.schemas.core import ActivoCreate, ActivoUpdate
from app.schemas.traceability import MovimientoCreate

class CoreService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CoreRepository(db)
        self.cat_repo = CatalogRepository(db)
        self.gov_repo = GovernanceRepository(db)
        self.trace_repo = TraceabilityRepository(db)

    async def create_activo(self, schema: ActivoCreate):
        # 1. LÓGICA DE SECUENCIAS
        if not schema.ACT_Codigo_Interno:
            tipo_activo = await self.cat_repo.get_tipo_activo_by_id(schema.TAC_Tipo_Activo)
            
            if not tipo_activo:
                raise HTTPException(status_code=404, detail="ASSET_TYPE_NOT_FOUND")
            
            if not tipo_activo.TAC_Prefijo:
                raise HTTPException(status_code=400, detail="ASSET_TYPE_HAS_NO_PREFIX_CONFIGURED_FOR_AUTO_GENERATION")
            
            contexto_secuencia = f"ASSET_{tipo_activo.TAC_Prefijo}"
            nuevo_codigo = await self.gov_repo.get_next_code(contexto=contexto_secuencia, prefijo=tipo_activo.TAC_Prefijo)
            schema.ACT_Codigo_Interno = nuevo_codigo

        # 2. VALIDACIONES DE INTEGRIDAD
        if await self.repo.get_by_codigo_interno(schema.ACT_Codigo_Interno):
            raise HTTPException(status_code=400, detail="ASSET_CODE_ALREADY_EXISTS")
        
        if await self.repo.get_by_serie(schema.ACT_Serie_Fabricante):
            raise HTTPException(status_code=400, detail="SERIAL_NUMBER_ALREADY_EXISTS")

        # 3. CREACIÓN
        nuevo_activo = await self.repo.create_activo(schema)

        # 4. TRAZABILIDAD AUTOMÁTICA
        q_tipo = select(TipoMovimiento).where(TipoMovimiento.TMO_Nombre.ilike("%Ingreso%"))
        res_tipo = await self.db.execute(q_tipo)
        tipo_mov = res_tipo.scalar_one_or_none()
        
        q_area = select(Area).where(Area.ARE_Nombre.ilike("%Bodega%"))
        res_area = await self.db.execute(q_area)
        area_bodega = res_area.scalar_one_or_none()

        q_persona = select(Persona).limit(1)
        res_persona = await self.db.execute(q_persona)
        persona_resp = res_persona.scalar_one_or_none()

        if tipo_mov and area_bodega and persona_resp:
            movimiento_inicial = MovimientoCreate(
                ACT_Activo=nuevo_activo.ACT_Activo,
                PER_Persona=persona_resp.PER_Persona,
                ARE_Area=area_bodega.ARE_Area,
                TMO_Tipo_Movimiento=tipo_mov.TMO_Tipo_Movimiento,
                MOV_Observacion="Alta inicial del activo en sistema (Automático)"
            )
            await self.trace_repo.create_movimiento_transactional(movimiento_inicial)
            await self.db.commit()

        return nuevo_activo

    async def update_activo(self, activo_id: uuid.UUID, schema: ActivoUpdate):
        # 1. Verificar existencia
        activo_actual = await self.repo.get_by_id(activo_id)
        if not activo_actual:
            raise HTTPException(status_code=404, detail="ASSET_NOT_FOUND")

        # 2. Validar colisión de Código
        if schema.ACT_Codigo_Interno and schema.ACT_Codigo_Interno != activo_actual.ACT_Codigo_Interno:
            if await self.repo.get_by_codigo_interno(schema.ACT_Codigo_Interno):
                raise HTTPException(status_code=400, detail="NEW_ASSET_CODE_ALREADY_EXISTS")

        # 3. Validar colisión de Serie
        if schema.ACT_Serie_Fabricante and schema.ACT_Serie_Fabricante != activo_actual.ACT_Serie_Fabricante:
            if await self.repo.get_by_serie(schema.ACT_Serie_Fabricante):
                raise HTTPException(status_code=400, detail="NEW_SERIAL_NUMBER_ALREADY_EXISTS")

        return await self.repo.update_activo(activo_id, schema)

    async def list_activos(self, skip: int, limit: int):
        return await self.repo.get_all(skip, limit)