from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, delete, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
import uuid

from app.repositories.base import BaseRepository
from app.models.organization import Departamento, Cargo, Persona, Usuario
from app.schemas.organization import (
    DepartamentoCreate, DepartamentoUpdate,
    CargoCreate, CargoUpdate,
    PersonaCreate, PersonaUpdate,
    UsuarioCreate, UsuarioUpdate
)
from app.core.security import get_password_hash


class DepartamentoRepository(BaseRepository):
    async def get_all(self) -> List[Departamento]:
        result = await self.db.execute(select(Departamento))
        return result.scalars().all()

    async def get_by_name(self, name: str) -> Optional[Departamento]:
        result = await self.db.execute(select(Departamento).where(Departamento.DEP_Nombre == name))
        return result.scalar_one_or_none()

    async def get_by_id(self, id: int) -> Optional[Departamento]:
        result = await self.db.execute(select(Departamento).where(Departamento.DEP_Departamento == id))
        return result.scalar_one_or_none()

    async def create(self, schema: DepartamentoCreate) -> Departamento:
        db_obj = Departamento(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.flush()
        return db_obj

    async def update(self, id: int, schema: DepartamentoUpdate) -> Optional[Departamento]:
        update_data = schema.model_dump(exclude_unset=True)
        if update_data:
            query = update(Departamento).where(Departamento.DEP_Departamento == id).values(**update_data)
            await self.db.execute(query)
            await self.db.flush()
        return await self.get_by_id(id)

    async def count_personas(self, dep_id: int) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(Persona).where(Persona.DEP_Departamento == dep_id)
        )
        return result.scalar_one()

    async def delete(self, id: int):
        query = delete(Departamento).where(Departamento.DEP_Departamento == id)
        await self.db.execute(query)
        await self.db.flush()


class CargoRepository(BaseRepository):
    async def get_all(self) -> List[Cargo]:
        result = await self.db.execute(select(Cargo))
        return result.scalars().all()

    async def get_by_id(self, id: int) -> Optional[Cargo]:
        result = await self.db.execute(select(Cargo).where(Cargo.CAR_Cargo == id))
        return result.scalar_one_or_none()

    async def create(self, schema: CargoCreate) -> Cargo:
        db_obj = Cargo(**schema.model_dump())
        self.db.add(db_obj)
        await self.db.flush()
        return db_obj

    async def update(self, id: int, schema: CargoUpdate) -> Optional[Cargo]:
        update_data = schema.model_dump(exclude_unset=True)
        if update_data:
            query = update(Cargo).where(Cargo.CAR_Cargo == id).values(**update_data)
            await self.db.execute(query)
            await self.db.flush()
        return await self.get_by_id(id)

    async def count_personas(self, cargo_id: int) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(Persona).where(Persona.CAR_Cargo == cargo_id)
        )
        return result.scalar_one()

    async def delete(self, id: int):
        query = delete(Cargo).where(Cargo.CAR_Cargo == id)
        await self.db.execute(query)
        await self.db.flush()


class PersonaRepository(BaseRepository):
    async def get_all(self, extra_filter=None) -> List[Persona]:
        query = select(Persona)
        if extra_filter is not None:
            query = query.where(extra_filter)
        result = await self.db.execute(query)
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
        await self.db.flush()
        return db_obj

    async def update(self, id: uuid.UUID, schema: PersonaUpdate) -> Optional[Persona]:
        update_data = schema.model_dump(exclude_unset=True)
        if update_data:
            query = update(Persona).where(Persona.PER_Persona == id).values(**update_data)
            await self.db.execute(query)
            await self.db.flush()
        return await self.get_by_id(id)

    async def has_usuario(self, persona_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            select(func.count()).select_from(Usuario).where(Usuario.PER_Persona == persona_id)
        )
        return result.scalar_one() > 0

    async def get_available_for_user(self, extra_filter=None) -> List[Persona]:
        """
        Retorna personas que NO tienen un registro en la tabla INV_USUARIO.
        SQL: SELECT * FROM INV_PERSONA p LEFT JOIN INV_USUARIO u ON ... WHERE u.ID IS NULL
        """
        query = (
            select(Persona)
            .outerjoin(Usuario, Persona.PER_Persona == Usuario.PER_Persona)
            .where(Usuario.USU_Usuario == None)
        )
        if extra_filter is not None:
            query = query.where(extra_filter)
        result = await self.db.execute(query)
        return result.scalars().all()
    
    
class UsuarioRepository(BaseRepository):
    async def get_all(self) -> List[Usuario]:
        query = select(Usuario).options(selectinload(Usuario.persona))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_by_username(self, username: str) -> Optional[Usuario]:
        query = select(Usuario).options(selectinload(Usuario.persona)).where(Usuario.USU_Username == username)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_by_id(self, id: uuid.UUID) -> Optional[Usuario]:
        query = select(Usuario).options(selectinload(Usuario.persona)).where(Usuario.USU_Usuario == id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_username_or_email(self, identifier: str) -> Optional[Usuario]:
        """
        Resuelve un usuario por su username o por el correo corporativo de su
        persona. Usado por el flujo de restablecimiento de contraseña.
        """
        from app.models.organization import Persona
        u = await self.get_by_username(identifier)
        if u:
            return u
        query = (
            select(Usuario)
            .options(selectinload(Usuario.persona))
            .join(Persona, Persona.PER_Persona == Usuario.PER_Persona)
            .where(Persona.PER_Email_Corporativo == identifier)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_persona_email(self, email: str) -> Optional[Usuario]:
        query = (
            select(Usuario)
            .options(selectinload(Usuario.persona))
            .join(Persona, Persona.PER_Persona == Usuario.PER_Persona)
            .where(func.lower(Persona.PER_Email_Corporativo) == email.strip().lower())
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create(self, schema: UsuarioCreate) -> Usuario:
        hashed_pwd = get_password_hash(schema.USU_Password) if schema.USU_Password else None
        
        # Passlib (argon2/bcrypt) embebe el salt dentro del hash;
        # no hace falta una columna USU_Salt aparte (eliminada en migración f1a2b3c4d5e6).
        db_obj = Usuario(
            USU_Alcance_Global=False,  # el servicio aplica el alcance validado
            USU_Username=schema.USU_Username,
            USU_Password_Hash=hashed_pwd,
            USU_Rol=schema.USU_Rol,
            USU_SSO_Habilitado=schema.USU_SSO_Habilitado,
            USU_SSO_Provider=schema.USU_SSO_Provider,
            PER_Persona=schema.PER_Persona
        )
        
        self.db.add(db_obj)
        await self.db.flush()
        # Recargar con relación persona para no dejar un objeto "tibio"
        # que rompe la serialización por MissingGreenlet.
        return await self.get_by_id(db_obj.USU_Usuario)

    async def update(self, id: uuid.UUID, schema: UsuarioUpdate, exclude: set[str] | None = None) -> Usuario:
        update_data = schema.model_dump(exclude_unset=True, exclude=exclude or None)

        if "USU_Password" in update_data:
            update_data["USU_Password_Hash"] = get_password_hash(update_data.pop("USU_Password"))

        # Sin campos que actualizar → no-op (evita "UPDATE ... SET  WHERE",
        # que es un error de sintaxis SQL). Consistente con los demás repos.
        if update_data:
            query = (
                update(Usuario)
                .where(Usuario.USU_Usuario == id)
                .values(**update_data)
            )
            await self.db.execute(query)
            await self.db.flush()

        return await self.get_by_id(id)
    
    async def count_active_super_admins(self) -> int:
        """Cuenta cuántos SUPER_ADMIN están activos en el sistema"""
        query = select(func.count()).select_from(Usuario).where(
            Usuario.USU_Rol == "SUPER_ADMIN",
            Usuario.USU_Estado == True
        )
        result = await self.db.execute(query)
        return result.scalar() or 0
