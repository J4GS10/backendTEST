"""
Servicio base.

Clase abstracta que estandariza el constructor del servicio y provee
utilidades comunes: acceso tipado al repositorio y un helper para
convertir errores de BD en DomainError legibles.

Patrón aplicado: Service Layer + Template Method.
Las subclases declaran `repo_class` y obtienen el repositorio correctamente
tipado sin repetir la inyección en cada __init__.

Uso:

    class CoreService(BaseService[CoreRepository]):
        repo_class = CoreRepository

        async def create_activo(self, data: ActivoCreate) -> Activo:
            return await self.repo.create_activo(data)

El helper `_not_found` lanza HTTPException 404 de forma uniforme.
"""
from __future__ import annotations

from typing import Generic, Optional, Type, TypeVar

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.transactional import transactional
from app.repositories.base import BaseRepository

R = TypeVar("R", bound=BaseRepository)


class BaseService(Generic[R]):
    """Servicio base con repositorio tipado e inyección estándar."""

    repo_class: Type[R]

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo: R = self.repo_class(db)

    # ── Helpers de error ────────────────────────────────────────────────────

    @staticmethod
    def _not_found(entity: str, identifier: object = None) -> HTTPException:
        detail = f"{entity} no encontrado"
        if identifier is not None:
            detail += f": {identifier}"
        return HTTPException(status_code=404, detail=detail)

    @staticmethod
    def _conflict(message: str) -> HTTPException:
        return HTTPException(status_code=409, detail=message)

    @staticmethod
    def _bad_request(message: str) -> HTTPException:
        return HTTPException(status_code=400, detail=message)

    # ── Shortcut de get-or-404 ──────────────────────────────────────────────

    async def get_or_404(self, pk: object, entity_name: str = "Registro"):
        instance = await self.repo.get_by_pk(pk)
        if instance is None:
            raise self._not_found(entity_name, pk)
        return instance
