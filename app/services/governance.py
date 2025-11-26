from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.governance import GovernanceRepository
from app.schemas.governance import ConfigUpdate

class GovernanceService:
    def __init__(self, db: AsyncSession):
        self.repo = GovernanceRepository(db)

    async def get_public_config(self):
        """Obtiene la configuración para el Login (Logo/Colores)"""
        return await self.repo.get_config()

    async def update_config(self, schema: ConfigUpdate):
        return await self.repo.update_config(schema)