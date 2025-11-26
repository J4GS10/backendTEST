from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
import uuid

from app.models.organization import Departamento, Cargo, Persona, Usuario
from app.schemas.organization import (
    DepartamentoCreate, CargoCreate, PersonaCreate, UsuarioCreate
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

class UsuarioRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_username(self, username: str) -> Optional[Usuario]:
        result = await self.db.execute(select(Usuario).where(Usuario.USU_Username == username))
        return result.scalar_one_or_none()

    async def create(self, schema: UsuarioCreate) -> Usuario:
        # Lógica de Seguridad: Hashing
        hashed_pwd = get_password_hash(schema.USU_Password)
        
        db_obj = Usuario(
            USU_Username=schema.USU_Username,
            USU_Password_Hash=hashed_pwd,
            USU_Salt="auto", # Passlib maneja el salt internamente en el hash bcrypt
            USU_Rol=schema.USU_Rol,
            PER_Persona=schema.PER_Persona
        )
        
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj