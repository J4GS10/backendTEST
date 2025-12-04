from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
from sqlalchemy.orm import selectinload
from typing import List, Optional
import uuid

from app.models.organization import Departamento, Cargo, Persona, Usuario
from app.schemas.organization import (
    DepartamentoCreate, CargoCreate, PersonaCreate, 
    UsuarioCreate, UsuarioUpdate
)
from app.core.security import get_password_hash

class DepartamentoRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> List[Departamento]:
        result = await self.db.execute(select(Departamento))
        return result.scalars().all()

    async def get_by_name(self, name: str) -> Optional[Departamento]:
        result = await self.db.execute(select(Departamento).where(Departamento.DEP_Nombre == name))
        return result.scalar_one_or_none()

    async def create(self, schema: DepartamentoCreate) -> Departamento:
        db_obj = Departamento(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

class CargoRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> List[Cargo]:
        result = await self.db.execute(select(Cargo))
        return result.scalars().all()

    async def create(self, schema: CargoCreate) -> Cargo:
        db_obj = Cargo(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

class PersonaRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> List[Persona]:
        result = await self.db.execute(select(Persona))
        return result.scalars().all()

    async def get_by_email(self, email: str) -> Optional[Persona]:
        result = await self.db.execute(select(Persona).where(Persona.PER_Email_Corporativo == email))
        return result.scalar_one_or_none()
    
    async def get_by_id(self, id: uuid.UUID) -> Optional[Persona]:
        result = await self.db.execute(select(Persona).where(Persona.PER_Persona == id))
        return result.scalar_one_or_none()

    async def create(self, schema: PersonaCreate) -> Persona:
        db_obj = Persona(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def get_available_for_user(self) -> List[Persona]:
        """
        Retorna personas que NO tienen un registro en la tabla INV_USUARIO.
        SQL: SELECT * FROM INV_PERSONA p LEFT JOIN INV_USUARIO u ON ... WHERE u.ID IS NULL
        """
        query = (
            select(Persona)
            .outerjoin(Usuario, Persona.PER_Persona == Usuario.PER_Persona)
            .where(Usuario.USU_Usuario == None)
        )
        result = await self.db.execute(query)
        return result.scalars().all()
    
    
class UsuarioRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> List[Usuario]:
        # Trae la persona para la tabla de usuarios
        query = select(Usuario).options(selectinload(Usuario.persona))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_by_username(self, username: str) -> Optional[Usuario]:
        # RESTAURADO: Traemos la persona también al hacer login.
        # Esto permite que el sistema sepa el nombre real del usuario autenticado.
        query = select(Usuario).options(selectinload(Usuario.persona)).where(Usuario.USU_Username == username)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_by_id(self, id: uuid.UUID) -> Optional[Usuario]:
        # También aquí es útil
        query = select(Usuario).options(selectinload(Usuario.persona)).where(Usuario.USU_Usuario == id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create(self, schema: UsuarioCreate) -> Usuario:
        hashed_pwd = get_password_hash(schema.USU_Password)
        
        db_obj = Usuario(
            USU_Username=schema.USU_Username,
            USU_Password_Hash=hashed_pwd,
            USU_Salt="auto",
            USU_Rol=schema.USU_Rol,
            PER_Persona=schema.PER_Persona
        )
        
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj

    async def update(self, id: uuid.UUID, schema: UsuarioUpdate) -> Usuario:
        update_data = schema.model_dump(exclude_unset=True)
        
        if "USU_Password" in update_data:
            update_data["USU_Password_Hash"] = get_password_hash(update_data.pop("USU_Password"))
            
        query = (
            update(Usuario)
            .where(Usuario.USU_Usuario == id)
            .values(**update_data)
        )
        await self.db.execute(query)
        await self.db.commit()
        
        return await self.get_by_id(id)
    
    async def count_active_super_admins(self) -> int:
        """Cuenta cuántos SUPER_ADMIN están activos en el sistema"""
        query = select(func.count()).select_from(Usuario).where(
            Usuario.USU_Rol == "SUPER_ADMIN",
            Usuario.USU_Estado == True
        )
        result = await self.db.execute(query)
        return result.scalar() or 0