"""Schemas reutilizables (envoltorios de paginación, etc.)."""
from __future__ import annotations

from typing import Generic, List, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Envoltorio estándar para listados paginados."""

    items: List[T] = Field(..., description="Página actual")
    total: int = Field(..., description="Total de registros que coinciden con el filtro")
    page: int = Field(..., ge=1, description="Página actual (1-indexed)")
    per_page: int = Field(..., ge=1, description="Tamaño de página solicitado")

    @property
    def pages(self) -> int:
        if self.per_page <= 0:
            return 0
        return (self.total + self.per_page - 1) // self.per_page
