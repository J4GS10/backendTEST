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


# =========================================================================
# Email corporativo
# =========================================================================
# `EmailStr` (email-validator) rechaza dominios de uso especial como `.local`,
# que es justamente el dominio más común de un Active Directory interno
# (svc@empresa.local). Para correos corporativos se valida la sintaxis de
# forma estricta pero se aceptan dominios internos. Los correos EXTERNOS
# (p. ej. proveedores) siguen usando EmailStr.
import re as _re
from typing import Annotated as _Annotated

from pydantic import AfterValidator as _AfterValidator

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_CORPORATE_EMAIL_RE = _re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@" + _LABEL + r"(?:\." + _LABEL + r")+$"
)


def _validate_corporate_email(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or not _CORPORATE_EMAIL_RE.match(value) or ".." in value.split("@")[0]:
        raise ValueError("value is not a valid email address")
    local, domain = value.rsplit("@", 1)
    return f"{local}@{domain.lower()}"


CorporateEmail = _Annotated[str, _AfterValidator(_validate_corporate_email)]

