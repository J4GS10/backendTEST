from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
import uuid

from app.repositories.organization import (
    DepartamentoRepository, CargoRepository, 
    PersonaRepository, UsuarioRepository
)
from app.schemas.organization import (
    DepartamentoCreate, CargoCreate, PersonaCreate, 
    UsuarioCreate, UsuarioUpdate
)

class OrganizationService:
    def __init__(self, db: AsyncSession):
        self.dep_repo = DepartamentoRepository(db)
        self.car_repo = CargoRepository(db)
        self.per_repo = PersonaRepository(db)
        self.usu_repo = UsuarioRepository(db)

    async def get_personas_disponibles(self):
        return await self.per_repo.get_available_for_user()

    # --- DEPARTAMENTO ---
    async def create_departamento(self, schema: DepartamentoCreate):
        existing = await self.dep_repo.get_by_name(schema.DEP_Nombre)
        if existing:
            raise HTTPException(status_code=400, detail="DEPARTMENT_ALREADY_EXISTS")
        return await self.dep_repo.create(schema)

    async def get_departamentos(self):
        return await self.dep_repo.get_all()

    # --- CARGO ---
    async def create_cargo(self, schema: CargoCreate):
        return await self.car_repo.create(schema)
    
    async def get_cargos(self):
        return await self.car_repo.get_all()

    # --- PERSONA ---
    async def create_persona(self, schema: PersonaCreate):
        existing = await self.per_repo.get_by_email(schema.PER_Email_Corporativo)
        if existing:
            raise HTTPException(status_code=400, detail="EMAIL_ALREADY_EXISTS")
        return await self.per_repo.create(schema)

    async def get_personas(self):
        return await self.per_repo.get_all()

    # --- USUARIO ---
    
    # ESTE MÉTODO FALTABA
    async def get_usuarios(self):
        return await self.usu_repo.get_all()

    async def create_usuario(self, schema: UsuarioCreate, requester_role: str):
        if schema.USU_Rol in ["SUPER_ADMIN", "ADMIN_TI"] and requester_role != "SUPER_ADMIN":
             raise HTTPException(status_code=403, detail="ONLY_SUPER_ADMIN_CAN_CREATE_ADMINS")

        persona = await self.per_repo.get_by_id(schema.PER_Persona)
        if not persona:
            raise HTTPException(status_code=404, detail="PERSONA_NOT_FOUND")
        
        existing = await self.usu_repo.get_by_username(schema.USU_Username)
        if existing:
            raise HTTPException(status_code=400, detail="USERNAME_ALREADY_EXISTS")
            
        return await self.usu_repo.create(schema)

    async def update_usuario(self, usuario_id: uuid.UUID, schema: UsuarioUpdate, requester_role: str):
        target_user = await self.usu_repo.get_by_id(usuario_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="USER_NOT_FOUND")

        # Regla 1: Protección de Jerarquía
        if target_user.USU_Rol == "SUPER_ADMIN" and requester_role != "SUPER_ADMIN":
             raise HTTPException(status_code=403, detail="CANNOT_MODIFY_SUPER_ADMIN")

        if requester_role == "ADMIN_TI" and target_user.USU_Rol not in ["TECNICO", "AUDITOR"]:
             raise HTTPException(status_code=403, detail="INSUFFICIENT_PERMISSIONS")

        # === PROTECCIÓN DE ÚLTIMO SUPER ADMIN ===
        will_disable = schema.USU_Estado is False
        will_demote = schema.USU_Rol and schema.USU_Rol != "SUPER_ADMIN"

        if target_user.USU_Rol == "SUPER_ADMIN" and (will_disable or will_demote):
            count = await self.usu_repo.count_active_super_admins()
            if count <= 1:
                raise HTTPException(
                    status_code=400, 
                    detail="CANNOT_DISABLE_LAST_SUPER_ADMIN"
                )
        # =====================================================

        return await self.usu_repo.update(usuario_id, schema)