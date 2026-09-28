"""Organización: Departamento, Cargo, Persona, Usuario. RBAC granular."""
from typing import List
import uuid
from fastapi import APIRouter, Depends, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_client_ip, require_admin, require_iam, require_super_admin
from app.core.limiter import limiter
from app.db.session import get_db
from app.schemas.organization import (
    CargoCreate, CargoResponse, CargoUpdate,
    DepartamentoCreate, DepartamentoResponse, DepartamentoUpdate,
    PersonaCreate, PersonaResponse, PersonaUpdate,
    UsuarioCreate, UsuarioResponse, UsuarioUpdate,
)
from app.services.organization import OrganizationService
from app.services.suggestions import SuggestionService

router = APIRouter()

ADMIN = [Depends(require_admin)]
SUPER = [Depends(require_super_admin)]
IAM = [Depends(require_iam)]


def get_service(db: AsyncSession = Depends(get_db)) -> OrganizationService:
    return OrganizationService(db)


def _ctx(request: Request, user: CurrentUser) -> dict:
    return {"usuario_id": user.USU_Usuario, "ip": get_client_ip(request)}


# ================= SEDES DEL ALCANCE =================
@router.get("/sedes")
async def sedes_en_alcance(db: AsyncSession = Depends(get_db)):
    """
    Sedes que el usuario puede ver (todas si su alcance es global). Alimenta
    los selectores de sede y la asignación de alcance en "Usuarios y accesos".
    """
    from app.services.location import LocationService
    return await LocationService(db).list_sedes_en_alcance()


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


# ================= USUARIOS — gestión de identidades (SUPER_ADMIN, ADMIN_SEGURIDAD) =================
# Separación de funciones: ADMIN_TI opera el inventario pero NO administra
# cuentas. Reglas de jerarquía en app/core/roles.py.
@router.get("/usuarios", response_model=List[UsuarioResponse], dependencies=IAM)
@limiter.limit("30/minute")
async def list_usuarios(request: Request, service: OrganizationService = Depends(get_service)):
    """Listado de usuarios con su estado de seguridad (MFA, bloqueo, contraseña)."""
    return await service.get_usuarios()


@router.get("/usuarios/seguridad/resumen", dependencies=IAM)
async def security_summary(service: OrganizationService = Depends(get_service)):
    """Indicadores del panel de seguridad (cobertura MFA, bloqueos…) y política vigente."""
    return await service.security_summary()


@router.get("/usuarios/{id}", response_model=UsuarioResponse, dependencies=IAM)
async def get_usuario(id: uuid.UUID, service: OrganizationService = Depends(get_service)):
    return await service.get_usuario(id)


@router.post("/usuarios", response_model=UsuarioResponse, status_code=201, dependencies=IAM)
async def create_usuario(
    schema: UsuarioCreate, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    return await service.create_usuario(
        schema, requester_role=current_user.USU_Rol, **_ctx(request, current_user)
    )


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioResponse, dependencies=IAM)
async def update_usuario(
    usuario_id: uuid.UUID, schema: UsuarioUpdate, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    return await service.update_usuario(
        usuario_id, schema, requester_role=current_user.USU_Rol, **_ctx(request, current_user)
    )


@router.post("/usuarios/{usuario_id}/password/reset", dependencies=IAM)
@limiter.limit("10/minute")
async def reset_usuario_password(
    usuario_id: uuid.UUID, request: Request, response: Response, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    """
    Genera una contraseña temporal (se devuelve UNA sola vez), obliga a
    cambiarla en el próximo inicio de sesión y cierra las sesiones abiertas.
    """
    temporal = await service.reset_password(
        usuario_id, requester_role=current_user.USU_Rol, **_ctx(request, current_user)
    )
    response.headers["Cache-Control"] = "no-store"
    return {"temporary_password": temporal}


@router.post("/usuarios/{usuario_id}/2fa/reset", dependencies=IAM)
async def reset_usuario_2fa(
    usuario_id: uuid.UUID, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    """Reset del MFA (p. ej. teléfono perdido). Cierra sus sesiones; si su rol
    exige MFA, deberá enrolar uno nuevo en el próximo inicio de sesión."""
    await service.reset_2fa(usuario_id, requester_role=current_user.USU_Rol, **_ctx(request, current_user))
    return {"status": "success", "message": "2FA_RESET"}


@router.post("/usuarios/{usuario_id}/unlock", dependencies=IAM)
async def unlock_usuario(
    usuario_id: uuid.UUID, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    """Desbloquea una cuenta bloqueada por intentos fallidos."""
    await service.unlock_usuario(usuario_id, requester_role=current_user.USU_Rol, **_ctx(request, current_user))
    return {"status": "success"}


@router.post("/usuarios/{usuario_id}/sessions/revoke", dependencies=IAM)
async def revoke_usuario_sessions(
    usuario_id: uuid.UUID, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    """Cierra todas las sesiones de la cuenta en todos sus dispositivos."""
    await service.revoke_sessions(usuario_id, requester_role=current_user.USU_Rol, **_ctx(request, current_user))
    return {"status": "success"}


@router.get("/usuarios/seguridad/sesiones", dependencies=IAM)
async def active_sessions(current_user: CurrentUser, service: OrganizationService = Depends(get_service)):
    """Sesiones activas de todas las cuentas (dispositivo, IP, última actividad)."""
    return await service.all_active_sessions(current_user.USU_Rol)


@router.get("/usuarios/{usuario_id}/sessions", dependencies=IAM)
async def usuario_sessions(
    usuario_id: uuid.UUID, current_user: CurrentUser, service: OrganizationService = Depends(get_service),
):
    """Sesiones activas de una cuenta."""
    return await service.list_user_sessions(
        usuario_id, requester_role=current_user.USU_Rol, requester_id=current_user.USU_Usuario,
    )


@router.delete("/usuarios/{usuario_id}/sessions/{session_id}", status_code=204, dependencies=IAM)
async def close_usuario_session(
    usuario_id: uuid.UUID, session_id: str, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    """Cierra una sesión concreta de otra cuenta (p. ej. un dispositivo no reconocido)."""
    await service.close_user_session(
        usuario_id, session_id, requester_role=current_user.USU_Rol, **_ctx(request, current_user)
    )


@router.delete("/usuarios/{usuario_id}", status_code=204, dependencies=IAM)
async def desactivar_usuario(
    usuario_id: uuid.UUID, request: Request, current_user: CurrentUser,
    service: OrganizationService = Depends(get_service),
):
    """Desactivación lógica (preserva auditoría)."""
    await service.desactivar_usuario(
        usuario_id, requester_role=current_user.USU_Rol, **_ctx(request, current_user)
    )


# ================= SUGERENCIAS PARA FORMULARIOS =================
@router.get("/personas/{id}/contexto")
async def persona_contexto(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Datos que se derivan de la persona: departamento, cargo, jefe, área
    habitual, activos en custodia, usuario, y usuario/rol sugeridos."""
    return await SuggestionService(db).persona(id)


@router.get("/departamentos/{id}/contexto")
async def departamento_contexto(id: int, db: AsyncSession = Depends(get_db)):
    """Cargo, jefe y área más probables para una persona nueva del departamento."""
    return await SuggestionService(db).departamento(id)
