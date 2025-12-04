from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update

from app.models.governance import ConfiguracionSistema, Secuencia
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

    async def get_next_code(self, contexto: str, prefijo: str, relleno: int = 5) -> str:
        """
        Genera el siguiente código único (Ej: LPT00001).
        Usa 'with_for_update()' para bloquear la fila y evitar duplicados en concurrencia.
        """
        # 1. Buscar y Bloquear
        query = select(Secuencia).where(Secuencia.SEC_Contexto == contexto).with_for_update()
        result = await self.db.execute(query)
        secuencia = result.scalar_one_or_none()

        if not secuencia:
            # Si no existe la secuencia para este prefijo, la creamos desde 0
            secuencia = Secuencia(
                SEC_Contexto=contexto,
                SEC_Ultimo_Numero=0,
                SEC_Relleno=relleno
            )
            self.db.add(secuencia)
            # Flush para obtener el ID y bloquear, aunque en insert el lock es implícito
            await self.db.flush() 
        
        # 2. Incrementar
        secuencia.SEC_Ultimo_Numero += 1
        
        # 3. Formatear
        # Ejemplo: LPT + 00001
        numero_str = str(secuencia.SEC_Ultimo_Numero).zfill(secuencia.SEC_Relleno)
        codigo_final = f"{prefijo}{numero_str}"
        
        # El commit se hará en la capa de servicio superior
        return codigo_final