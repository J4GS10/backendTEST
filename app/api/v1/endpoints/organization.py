"""Organización: Departamento, Cargo, Persona, Usuario. RBAC granular."""
from typing import List
import uuid
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_client_ip, require_admin, require_super_admin
from app.core.limiter import limiter
from app.db.session import get_db
from app.schemas.organization import (
    CargoCreate, CargoResponse, CargoUpdate,
    DepartamentoCreate, DepartamentoResponse, DepartamentoUpdate,
    PersonaCreate, PersonaResponse, PersonaUpdate,
    UsuarioCreate, UsuarioResponse, UsuarioUpdate,
)
from app.services.organization import OrganizationService

router = APIRouter()

ADMIN = [Depends(require_admin)]
SUPER = [Depends(require_super_admin)]


def get_service(db: AsyncSession = Depends(get_db)) -> OrganizationService:
    return OrganizationService(db)


def _ctx(request: Request, user: CurrentUser) -> dict:
    return {"usuario_id": user.USU_Usuario, "ip": get_client_ip(request)}


# ================= DEPARTAMENTOS =================
@router.get("/departamentos/resumen")
@limiter.limit("10/minute")
async def departamentos_resumen(request: Request, service: OrganizationService = Depends(get_service)):
    """
    Lista de departamentos con conteo de personas activas, activos asignados
    y desglose por tipo de activo. Pensado para una vista dashboard organizacional.
    Rate-limit estricto: agregación costosa (multiples JOIN + GROUP BY).
    """
    return await service.departamentos_resumen()


@router.get("/departamentos/{id}/detalle")
@limiter.limit("10/minute")
async def get_departamento_detalle(id: int, request: Request, service: OrganizationService = Depends(get_service)):
    """
    Detalle del departamento: lista de personas con los activos que tienen asignados.
    Útil para "¿qué tiene este departamento?".
    """
    return await service.departamento_detalle(id)


@router.get("/departamentos", response_model=List[DepartamentoResponse])
async def list_departamentos(service: OrganizationService = Depends(get_service)):
    return await service.get_departamentos()


@router.get("/departamentos/{id}", response_model=DepartamentoResponse)
async def get_departamento(id: int, service: OrganizationService = Depends(get_service)):
    return await service.get_departamento(id)


@router.post("/departamentos", response_model=DepartamentoResponse, status_code=201, dependencies=ADMIN)
async def create_departamento(
    schema: DepartamentoCreate, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    return await service.create_departamento(schema, **_ctx(request, current_user))


@router.patch("/departamentos/{id}", response_model=DepartamentoResponse, dependencies=ADMIN)
async def update_departamento(
    id: int, schema: DepartamentoUpdate, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    return await service.update_departamento(id, schema, **_ctx(request, current_user))


@router.delete("/departamentos/{id}", status_code=204, dependencies=ADMIN)
async def delete_departamento(
    id: int, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    await service.delete_departamento(id, **_ctx(request, current_user))


# ================= CARGOS =================
@router.get("/cargos", response_model=List[CargoResponse])
async def list_cargos(service: OrganizationService = Depends(get_service)):
    return await service.get_cargos()


@router.get("/cargos/{id}", response_model=CargoResponse)
async def get_cargo(id: int, service: OrganizationService = Depends(get_service)):
    return await service.get_cargo(id)


@router.post("/cargos", response_model=CargoResponse, status_code=201, dependencies=ADMIN)
async def create_cargo(
    schema: CargoCreate, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    return await service.create_cargo(schema, **_ctx(request, current_user))


@router.patch("/cargos/{id}", response_model=CargoResponse, dependencies=ADMIN)
async def update_cargo(
    id: int, schema: CargoUpdate, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    return await service.update_cargo(id, schema, **_ctx(request, current_user))


@router.delete("/cargos/{id}", status_code=204, dependencies=ADMIN)
async def delete_cargo(
    id: int, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    await service.delete_cargo(id, **_ctx(request, current_user))


# ================= PERSONAS =================
@router.get("/personas", response_model=List[PersonaResponse])
@limiter.limit("20/minute")
async def list_personas(request: Request, service: OrganizationService = Depends(get_service)):
    """Listado con PII (nombres, emails). Rate-limit para frenar scraping."""
    return await service.get_personas()


@router.get("/personas/disponibles", response_model=List[PersonaResponse])
@limiter.limit("20/minute")
async def list_personas_disponibles(request: Request, service: OrganizationService = Depends(get_service)):
    """Personas sin usuario asignado."""
    return await service.get_personas_disponibles()


@router.get("/personas/{id}", response_model=PersonaResponse)
async def get_persona(id: uuid.UUID, service: OrganizationService = Depends(get_service)):
    return await service.get_persona(id)


@router.post("/personas", response_model=PersonaResponse, status_code=201, dependencies=ADMIN)
async def create_persona(
    schema: PersonaCreate, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    return await service.create_persona(schema, **_ctx(request, current_user))


@router.patch("/personas/{id}", response_model=PersonaResponse, dependencies=ADMIN)
async def update_persona(
    id: uuid.UUID, schema: PersonaUpdate, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    return await service.update_persona(id, schema, **_ctx(request, current_user))


@router.delete("/personas/{id}", status_code=204, dependencies=ADMIN)
async def delete_persona(
    id: uuid.UUID, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    await service.delete_persona(id, **_ctx(request, current_user))


# ================= USUARIOS — SUPER_ADMIN o ADMIN_TI =================
@router.get("/usuarios", response_model=List[UsuarioResponse], dependencies=ADMIN)
@limiter.limit("20/minute")
async def list_usuarios(request: Request, service: OrganizationService = Depends(get_service)):
    """Listado de usuarios (incluye username + rol). Rate-limit para frenar scraping."""
    return await service.get_usuarios()


@router.get("/usuarios/{id}", response_model=UsuarioResponse, dependencies=ADMIN)
async def get_usuario(id: uuid.UUID, service: OrganizationService = Depends(get_service)):
    return await service.get_usuario(id)


@router.post("/usuarios", response_model=UsuarioResponse, status_code=201, dependencies=ADMIN)
async def create_usuario(
    schema: UsuarioCreate, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    return await service.create_usuario(
        schema, requester_role=current_user.USU_Rol, **_ctx(request, current_user)
    )


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioResponse, dependencies=ADMIN)
async def update_usuario(
    usuario_id: uuid.UUID, schema: UsuarioUpdate, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    return await service.update_usuario(
        usuario_id, schema, requester_role=current_user.USU_Rol, **_ctx(request, current_user)
    )


@router.post("/usuarios/{usuario_id}/2fa/reset", dependencies=SUPER)
async def reset_usuario_2fa(
    usuario_id: uuid.UUID, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    """Reset administrativo del 2FA de un usuario (solo SUPER_ADMIN).

    Útil cuando el empleado pierde su segundo factor. Limpia método/secret,
    códigos de recuperación y OTPs de email; el usuario re-enrola en su próximo
    login si su rol lo exige.
    """
    await service.reset_2fa(usuario_id, **_ctx(request, current_user))
    return {"status": "success", "message": "2FA_RESET"}


@router.delete("/usuarios/{usuario_id}", status_code=204, dependencies=ADMIN)
async def desactivar_usuario(
    usuario_id: uuid.UUID, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    """Desactivación lógica (preserva auditoría)."""
    await service.desactivar_usuario(
        usuario_id, requester_role=current_user.USU_Rol, **_ctx(request, current_user)
    )
