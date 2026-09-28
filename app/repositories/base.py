"""
Repositorio base genérico.

Proporciona operaciones CRUD estándar para cualquier modelo SQLAlchemy.
Los repositorios concretos heredan de esta clase y agregan queries específicas
de dominio sin repetir la lógica común (get_by_id, create, update, delete,
list con paginación).

Patrón aplicado: Template Method — las subclases override `_pk_column()` y
opcionalmente `_apply_eager_loads()` para definir cómo se carga cada modelo.
"""
from __future__ import annotations

import uuid
from typing import Any, Generic, Optional, Sequence, Tuple, Type, TypeVar

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

M = TypeVar("M")  # SQLAlchemy model
PK = TypeVar("PK", uuid.UUID, int, str)


class BaseRepository(Generic[M]):
    """
    Repositorio genérico. Herencia:

        class CoreRepository(BaseRepository[Activo]):
            model = Activo

            def _pk_column(self):
                return Activo.ACT_Activo

    El tipo genérico M es solo para type-checking; en runtime se usa `self.model`.
    """

    model: Type[M]

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Método a override obligatorio ───────────────────────────────────────

    def _pk_column(self) -> Any:
        """Devuelve la columna PK del modelo. Ej: Activo.ACT_Activo"""
        raise NotImplementedError(
            f"{self.__class__.__name__} debe implementar _pk_column()"
        )

    # ── Hook opcional para eager-loading ───────────────────────────────────

    def _apply_eager_loads(self, stmt: Any) -> Any:
        """Override para agregar selectinload/joinedload a las consultas get."""
        return stmt

    # ── CRUD genérico ───────────────────────────────────────────────────────

    async def get_by_pk(self, pk: Any) -> Optional[M]:
        stmt = self._apply_eager_loads(
            select(self.model).where(self._pk_column() == pk)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_pk_simple(self, pk: Any) -> Optional[M]:
        """Consulta ligera sin eager-loads, para validaciones internas."""
        stmt = select(self.model).where(self._pk_column() == pk)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_all(self) -> Sequence[M]:
        stmt = select(self.model)
        return (await self.db.execute(stmt)).scalars().all()

    async def list_paginated(
        self, *, page: int = 1, per_page: int = 25
    ) -> Tuple[Sequence[M], int]:
        """Retorna (items, total). page es 1-indexed."""
        offset = (page - 1) * per_page
        count_stmt = select(func.count()).select_from(self.model)
        total: int = (await self.db.execute(count_stmt)).scalar_one()
        data_stmt = select(self.model).offset(offset).limit(per_page)
        items = (await self.db.execute(data_stmt)).scalars().all()
        return items, total

    async def create(self, data: dict[str, Any]) -> M:
        """Crea una instancia sin commitear — la transacción decide."""
        instance = self.model(**data)
        self.db.add(instance)
        await self.db.flush()
        return instance

    async def update_by_pk(self, pk: Any, data: dict[str, Any]) -> Optional[M]:
        """Actualiza campos en la BD y retorna el objeto refrescado."""
        await self.db.execute(
            update(self.model)
            .where(self._pk_column() == pk)
            .values(**data)
        )
        return await self.get_by_pk(pk)

    async def delete_by_pk(self, pk: Any) -> bool:
        """Elimina por PK. Retorna True si existía, False si no."""
        result = await self.db.execute(
            delete(self.model).where(self._pk_column() == pk)
        )
        return result.rowcount > 0

    async def exists(self, pk: Any) -> bool:
        stmt = select(func.count()).select_from(self.model).where(
            self._pk_column() == pk
        )
        count: int = (await self.db.execute(stmt)).scalar_one()
        return count > 0
