from fastapi import APIRouter
from app.api.v1.endpoints import (
    login, 
    organization, 
    location, 
    catalogs, 
    core, 
    traceability, 
    software,   
    governance,
    stats
)

api_router = APIRouter()

# Incluimos el router de organización con un tag para documentación

# 1. Auth
api_router.include_router(login.router, tags=["Autenticación"])

# 2. Configuración (Debe ser público el GET)
api_router.include_router(governance.router, prefix="/gov", tags=["Gobierno y Configuración"])

# 3. Módulos de Negocio
api_router.include_router(organization.router, prefix="/org", tags=["Organización"])
api_router.include_router(location.router, prefix="/geo", tags=["Ubicación Geográfica"])
api_router.include_router(catalogs.router, prefix="/cat", tags=["Catálogos Técnicos"])
api_router.include_router(core.router, prefix="/core", tags=["Core Inventario"])
api_router.include_router(traceability.router, prefix="/trazabilidad", tags=["Trazabilidad"])
api_router.include_router(software.router, prefix="/soft", tags=["Software y Licencias"])

#4. Dashboard

api_router.include_router(stats.router, prefix="/stats", tags=["Dashboard y Métricas"])