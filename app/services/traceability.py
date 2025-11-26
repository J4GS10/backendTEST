from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.traceability import TraceabilityRepository
from app.schemas.traceability import MovimientoCreate, TipoMovimientoCreate

class TraceabilityService:
    def __init__(self, db: AsyncSession):
        self.repo = TraceabilityRepository(db)
        self.db = db # Necesitamos acceso directo a la sesión para el COMMIT final

    async def create_tipo_movimiento(self, schema: TipoMovimientoCreate):
        return await self.repo.create_tipo_movimiento(schema)
    
    async def list_tipos_movimiento(self):
        return await self.repo.get_tipos_movimiento()

    async def registrar_movimiento(self, schema: MovimientoCreate):
        """
        Lógica ACID:
        1. Buscar si el activo ya está asignado.
        2. Si sí, cerrar esa asignación anterior.
        3. Crear la nueva asignación.
        4. Commit atómico.
        """
        try:
            # Paso 1: Buscar vigente
            movimiento_vigente = await self.repo.get_movimiento_vigente(schema.ACT_Activo)
            
            # Paso 2: Cerrar anterior (Si existe)
            if movimiento_vigente:
                await self.repo.cerrar_movimiento(movimiento_vigente.MOV_Movimiento)
            
            # Paso 3: Crear nuevo
            nuevo_movimiento = await self.repo.create_movimiento_transactional(schema)
            
            # Paso 4: Confirmar todo junto
            await self.db.commit()
            await self.db.refresh(nuevo_movimiento)
            
            return nuevo_movimiento

        except Exception as e:
            await self.db.rollback() # Si falla algo, nada cambia
            raise HTTPException(status_code=500, detail=f"TRANSACTION_FAILED: {str(e)}")