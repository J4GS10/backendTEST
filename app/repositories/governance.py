from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update

from app.models.governance import ConfiguracionSistema
from app.schemas.governance import ConfigUpdate

class GovernanceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_config(self) -> ConfiguracionSistema:
        # Siempre buscamos el ID 1
        result = await self.db.execute(select(ConfiguracionSistema).where(ConfiguracionSistema.SYS_Configuracion == 1))
        config = result.scalar_one_or_none()
        
        if not config:
            # Si no existe (primer arranque), lo creamos con defaults
            config = ConfiguracionSistema(SYS_Configuracion=1)
            self.db.add(config)
            await self.db.commit()
            await self.db.refresh(config)
        
        return config

    async def update_config(self, schema: ConfigUpdate) -> ConfiguracionSistema:
        # Aseguramos que exista
        await self.get_config() 
        
        update_data = schema.model_dump(exclude_unset=True)
        if update_data:
            query = (
                update(ConfiguracionSistema)
                .where(ConfiguracionSistema.SYS_Configuracion == 1)
                .values(**update_data)
            )
            await self.db.execute(query)
            await self.db.commit()
            
        return await self.get_config()