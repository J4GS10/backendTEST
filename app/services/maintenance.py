from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.maintenance import MaintenanceRepository
from app.schemas.maintenance import MantenimientoCreate, TipoMantenimientoCreate

class MaintenanceService:
    def __init__(self, db: AsyncSession):
        self.repo = MaintenanceRepository(db)

    async def create_tipo(self, schema: TipoMantenimientoCreate):
        return await self.repo.create_tipo(schema)

    async def list_tipos(self):
        return await self.repo.get_tipos()

    async def registrar_mantenimiento(self, schema: MantenimientoCreate):
        # Aquí podríamos agregar lógica como:
        # "Cambiar estado del activo a 'En Reparación'"
        return await self.repo.create_mantenimiento(schema)

    async def list_mantenimientos(self):
        return await self.repo.get_all()