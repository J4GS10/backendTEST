from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.governance import GovernanceService
from app.schemas.governance import ConfigResponse, ConfigUpdate
from app.api import deps 

router = APIRouter()

def get_service(db: AsyncSession = Depends(get_db)) -> GovernanceService:
    return GovernanceService(db)

@router.get("/config", response_model=ConfigResponse)
async def get_config(service: GovernanceService = Depends(get_service)):
    """Endpoint público para cargar estilos del Frontend"""
    return await service.get_public_config()

@router.put("/config", response_model=ConfigResponse)
async def update_config(
    schema: ConfigUpdate, 
    service: GovernanceService = Depends(get_service),
    # Solo SUPER_ADMIN puede cambiar esto (Lógica de Seguridad)
    current_user = Depends(deps.RoleChecker(["SUPER_ADMIN"])) 
):
    return await service.update_config(schema)