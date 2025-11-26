from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.software import SoftwareRepository
from app.schemas.software import (
    TipoLicenciaCreate, SoftwareCreate, LicenciaCreate, InstalacionCreate
)

class SoftwareService:
    def __init__(self, db: AsyncSession):
        self.repo = SoftwareRepository(db)
        self.db = db # Acceso directo para transacción

    # --- CRUDs Básicos ---
    async def create_tipo_licencia(self, schema: TipoLicenciaCreate):
        return await self.repo.create_tipo_licencia(schema)
    
    async def list_tipos_licencia(self):
        return await self.repo.get_tipos_licencia()

    async def create_software(self, schema: SoftwareCreate):
        # Aquí podríamos validar unicidad de Nombre + Versión
        return await self.repo.create_software(schema)
    
    async def list_software(self):
        return await self.repo.get_software_all()

    async def create_licencia(self, schema: LicenciaCreate):
        return await self.repo.create_licencia(schema)
    
    async def list_licencias(self, software_id: int):
        return await self.repo.get_licencias_by_software(software_id)

    # --- LÓGICA DE AUTOMATIZACIÓN (Install) ---
    async def registrar_instalacion(self, schema: InstalacionCreate):
        """
        Automatización:
        1. Verifica duplicidad (¿Ya tiene esta licencia?).
        2. Verifica Disponibilidad (Total > Usada).
        3. Registra Instalación.
        4. Actualiza Contador de Licencia.
        5. Commit Atómico.
        """
        try:
            # 1. Validar Duplicidad
            existe = await self.repo.get_instalacion_existente(schema.ACT_Activo, schema.LIC_Licencia)
            if existe:
                raise HTTPException(status_code=400, detail="LICENSE_ALREADY_INSTALLED_ON_ASSET")

            # 2. Validar Disponibilidad
            licencia = await self.repo.get_licencia_by_id(schema.LIC_Licencia)
            if not licencia:
                raise HTTPException(status_code=404, detail="LICENSE_NOT_FOUND")
            
            if licencia.LIC_Cantidad_Usada >= licencia.LIC_Cantidad_Total:
                raise HTTPException(status_code=409, detail="NO_LICENSE_SEATS_AVAILABLE")

            # 3. Crear Registro
            nueva_instalacion = await self.repo.create_instalacion(schema)

            # 4. Actualizar Contador
            await self.repo.incrementar_uso_licencia(licencia.LIC_Licencia)

            # 5. Commit
            await self.db.commit()
            await self.db.refresh(nueva_instalacion)
            return nueva_instalacion

        except Exception as e:
            await self.db.rollback()
            # Re-lanzar si es HTTPException, sino crear uno nuevo
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status_code=500, detail=str(e))