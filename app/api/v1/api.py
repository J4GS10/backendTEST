from fastapi import APIRouter, Depends
from app.api.v1.endpoints import (
    login,
    organization,
    location,
    catalogs,
    core,
    traceability,
    software,
    governance,
    stats,
    maintenance,
    export,
    consumable,
    attachment,
    procurement,
    twofactor,
)
from app.api import deps

api_router = APIRouter()

# 1. Auth (Público)
api_router.include_router(login.router, tags=["Autenticación"])
# 1b. 2FA del usuario autenticado (/me/2fa/*) — JWT requerido en cada endpoint.
api_router.include_router(twofactor.router, tags=["2FA"])

# 2. Gobierno (GET público para cargar tema visual antes del login)
api_router.include_router(governance.router, prefix="/gov", tags=["Gobierno"])

# 3. Módulos de Negocio (Requieren autenticación JWT)
_auth = [Depends(deps.get_current_user)]

api_router.include_router(
    organization.router, prefix="/org", tags=["Organización"],
    dependencies=_auth
)
api_router.include_router(
    location.router, prefix="/geo", tags=["Ubicación Geográfica"],
    dependencies=_auth
)
api_router.include_router(
    catalogs.router, prefix="/cat", tags=["Catálogos Técnicos"],
    dependencies=_auth
)
api_router.include_router(
    core.router, prefix="/core", tags=["Core Inventario"],
    dependencies=_auth
)
api_router.include_router(
    traceability.router, prefix="/trazabilidad", tags=["Trazabilidad"],
    dependencies=_auth
)
api_router.include_router(
    software.router, prefix="/soft", tags=["Software y Licencias"],
    dependencies=_auth
)
api_router.include_router(
    maintenance.router, prefix="/mantenimiento", tags=["Mantenimiento y Soporte"],
    dependencies=_auth
)
api_router.include_router(
    consumable.router, prefix="/consumibles", tags=["Consumibles"],
    dependencies=_auth
)
api_router.include_router(
    attachment.router, prefix="/adjuntos", tags=["Adjuntos"],
    dependencies=_auth
)
api_router.include_router(
    procurement.router, prefix="/compras", tags=["Compras y Garantías"],
    dependencies=_auth
)

# 4. Dashboard (Requiere autenticación)
api_router.include_router(
    stats.router, prefix="/stats", tags=["Dashboard y Métricas"],
    dependencies=_auth
)

# Exportes CSV
api_router.include_router(
    export.router, prefix="/export", tags=["Exportación CSV"],
    dependencies=_auth,
)