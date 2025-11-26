from fastapi import FastAPI
from app.core.config import settings
from app.api.v1.api import api_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="API REST para el Sistema de Gestión de Inventario TI",
    version="1.0.0",
)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/health")
async def health_check():
    """
    Endpoint de monitoreo básico.
    Utilizado por Docker o Balanceadores de Carga para saber si el servicio está vivo.
    """
    return {
        "status": "active",
        "app_name": settings.PROJECT_NAME,
        "version": "1.0.0"
    }