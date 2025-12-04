from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.traceability import TraceabilityRepository
from app.schemas.traceability import MovimientoCreate, TipoMovimientoCreate

class TraceabilityService:
    def __init__(self, db: AsyncSession):
        self.repo = TraceabilityRepository(db)
        self.db = db  # Necesitamos acceso directo a la sesión para el COMMIT final

    async def create_tipo_movimiento(self, schema: TipoMovimientoCreate):
        return await self.repo.create_tipo_movimiento(schema)
    
    async def list_tipos_movimiento(self):
        return await self.repo.get_tipos_movimiento()

    async def list_movimientos(self):
        return await self.repo.get_all_movimientos()

    async def registrar_movimiento(self, schema: MovimientoCreate):
        """
        Lógica ACID Transaccional:
        1. Buscar si el activo ya está asignado.
        2. Si sí, cerrar esa asignación anterior.
        3. Crear la nueva asignación.
        4. Commit atómico.
        5. Recarga completa de relaciones (Fix MissingGreenlet).
        """
        try:

            movimiento_vigente = await self.repo.get_movimiento_vigente(schema.ACT_Activo)

            if movimiento_vigente:
                await self.repo.cerrar_movimiento(movimiento_vigente.MOV_Movimiento)
 
            nuevo_movimiento = await self.repo.create_movimiento_transactional(schema)

            await self.db.commit()

            movimiento_completo = await self.repo.get_by_id_full(nuevo_movimiento.MOV_Movimiento)
            
            return movimiento_completo

        except Exception as e:
            await self.db.rollback() 

            if isinstance(e, HTTPException):
                raise e

            raise HTTPException(status_code=500, detail=f"TRANSACTION_FAILED: {str(e)}")