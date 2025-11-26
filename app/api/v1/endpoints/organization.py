from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.db.session import get_db
from app.api import deps
from app.services.organization import OrganizationService
from app.schemas.organization import (
    DepartamentoResponse, DepartamentoCreate, 
    CargoResponse, CargoCreate,
    PersonaResponse, PersonaCreate,
    UsuarioResponse, UsuarioCreate, UsuarioUpdate
)

router = APIRouter()

def get_service(db: AsyncSession = Depends(get_db)) -> OrganizationService:
    return OrganizationService(db)

# === DEPARTAMENTOS ===
@router.post("/departamentos", response_model=DepartamentoResponse, status_code=201)
async def create_departamento(schema: DepartamentoCreate, service: OrganizationService = Depends(get_service)):
    return await service.create_departamento(schema)

@router.get("/departamentos", response_model=List[DepartamentoResponse])
async def list_departamentos(service: OrganizationService = Depends(get_service)):
    return await service.get_departamentos()

# === CARGOS ===
@router.post("/cargos", response_model=CargoResponse, status_code=201)
async def create_cargo(schema: CargoCreate, service: OrganizationService = Depends(get_service)):
    return await service.create_cargo(schema)

@router.get("/cargos", response_model=List[CargoResponse])
async def list_cargos(service: OrganizationService = Depends(get_service)):
    return await service.get_cargos()

# === PERSONAS ===
@router.post("/personas", response_model=PersonaResponse, status_code=201)
async def create_persona(schema: PersonaCreate, service: OrganizationService = Depends(get_service)):
    return await service.create_persona(schema)

@router.get("/personas", response_model=List[PersonaResponse])
async def list_personas(service: OrganizationService = Depends(get_service)):
    return await service.get_personas()

# === USUARIOS (Gestión Crítica) ===

@router.post("/usuarios", response_model=UsuarioResponse, status_code=201)
async def create_usuario(
    schema: UsuarioCreate, 
    service: OrganizationService = Depends(get_service),
    # Inyectamos el usuario actual para validar su rol
    current_user = Depends(deps.get_current_user)
):
    # Pre-validación: Solo admins pueden crear usuarios
    if current_user.USU_Rol not in ["SUPER_ADMIN", "ADMIN_TI"]:
        raise HTTPException(status_code=403, detail="NOT_AUTHORIZED")
        
    return await service.create_usuario(schema, requester_role=current_user.USU_Rol)

@router.patch("/usuarios/{usuario_id}", response_model=UsuarioResponse)
async def update_usuario(
    usuario_id: uuid.UUID,
    schema: UsuarioUpdate,
    service: OrganizationService = Depends(get_service),
    current_user = Depends(deps.get_current_user)
):
    """
    Endpoint para desactivar usuarios (Kill Switch) o cambiar contraseñas.
    """
    if current_user.USU_Rol not in ["SUPER_ADMIN", "ADMIN_TI"]:
        raise HTTPException(status_code=403, detail="NOT_AUTHORIZED")

    return await service.update_usuario(usuario_id, schema, requester_role=current_user.USU_Rol)