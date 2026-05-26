from typing import List
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentUser,
    get_client_ip,
    require_admin,
    require_operativo,
)
from app.api.idempotency import idempotency_guard, _IdempotencyGuard
from app.core.limiter import limiter
from app.db.session import get_db
from app.schemas.software import (
    InstalacionCreate,
    InstalacionDetalleResponse,
    InstalacionResponse,
    LicenciaCreate,
    LicenciaResponse,
    LicenciaUpdate,
    SoftwareCreate,
    SoftwareResponse,
    SoftwareUpdate,
    TipoLicenciaCreate,
    TipoLicenciaResponse,
    TipoLicenciaUpdate,
)
import uuid as _uuid
from app.services.software import SoftwareService

router = APIRouter()


def get_service(db: AsyncSession = Depends(get_db)) -> SoftwareService:
    return SoftwareService(db)


# --- TIPOS LICENCIA ---
@router.post(
    "/tipos-licencia", response_model=TipoLicenciaResponse, status_code=201,
    dependencies=[Depends(require_admin)],
)
async def create_tipo_licencia(
    schema: TipoLicenciaCreate,
    request: Request,
    current_user: CurrentUser,
    service: SoftwareService = Depends(get_service),
):
    return await service.create_tipo_licencia(
        schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request)
    )


@router.get("/tipos-licencia", response_model=List[TipoLicenciaResponse])
async def list_tipos_licencia(service: SoftwareService = Depends(get_service)):
    return await service.list_tipos_licencia()


@router.get("/tipos-licencia/{id}", response_model=TipoLicenciaResponse)
async def get_tipo_licencia(id: int, service: SoftwareService = Depends(get_service)):
    obj = await service.repo.get_tipo_licencia_by_id(id)
    if not obj:
        from fastapi import HTTPException
        raise HTTPException(404, "LICENSE_TYPE_NOT_FOUND")
    return obj


@router.patch(
    "/tipos-licencia/{id}", response_model=TipoLicenciaResponse,
    dependencies=[Depends(require_admin)],
)
async def update_tipo_licencia(
    id: int,
    schema: TipoLicenciaUpdate,
    request: Request,
    current_user: CurrentUser,
    service: SoftwareService = Depends(get_service),
):
    return await service.update_tipo_licencia(
        id, schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request)
    )


@router.delete(
    "/tipos-licencia/{id}", status_code=204,
    dependencies=[Depends(require_admin)],
)
async def delete_tipo_licencia(
    id: int,
    request: Request,
    current_user: CurrentUser,
    service: SoftwareService = Depends(get_service),
):
    await service.delete_tipo_licencia(
        id, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request)
    )


# --- SOFTWARE ---
@router.post(
    "/software", response_model=SoftwareResponse, status_code=201,
    dependencies=[Depends(require_admin)],
)
async def create_software(
    schema: SoftwareCreate,
    request: Request,
    current_user: CurrentUser,
    service: SoftwareService = Depends(get_service),
):
    return await service.create_software(
        schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request)
    )


@router.get("/software", response_model=List[SoftwareResponse])
async def list_software(service: SoftwareService = Depends(get_service)):
    return await service.list_software()


@router.get("/software/{id}", response_model=SoftwareResponse)
async def get_software(id: int, service: SoftwareService = Depends(get_service)):
    obj = await service.repo.get_software_by_id(id)
    if not obj:
        from fastapi import HTTPException
        raise HTTPException(404, "SOFTWARE_NOT_FOUND")
    return obj


@router.patch(
    "/software/{id}", response_model=SoftwareResponse,
    dependencies=[Depends(require_admin)],
)
async def update_software(
    id: int,
    schema: SoftwareUpdate,
    request: Request,
    current_user: CurrentUser,
    service: SoftwareService = Depends(get_service),
):
    return await service.update_software(
        id, schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request)
    )


@router.delete(
    "/software/{id}", status_code=204,
    dependencies=[Depends(require_admin)],
)
async def delete_software(
    id: int,
    request: Request,
    current_user: CurrentUser,
    service: SoftwareService = Depends(get_service),
):
    await service.delete_software(
        id, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request)
    )


# --- LICENCIAS ---
@router.post(
    "/licencias", response_model=LicenciaResponse, status_code=201,
    dependencies=[Depends(require_admin)],
)
async def create_licencia(
    schema: LicenciaCreate,
    request: Request,
    current_user: CurrentUser,
    service: SoftwareService = Depends(get_service),
):
    return await service.create_licencia(
        schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request)
    )


@router.get("/licencias", response_model=List[LicenciaResponse])
async def list_licencias(
    software_id: int = Query(...),
    service: SoftwareService = Depends(get_service),
):
    return await service.list_licencias(software_id)


@router.get("/licencias/{id}", response_model=LicenciaResponse)
async def get_licencia(id: int, service: SoftwareService = Depends(get_service)):
    return await service.get_licencia(id)


@router.patch("/licencias/{id}", response_model=LicenciaResponse, dependencies=[Depends(require_admin)])
async def update_licencia(
    id: int,
    schema: LicenciaUpdate,
    request: Request, current_user: CurrentUser,
    service: SoftwareService = Depends(get_service),
):
    return await service.update_licencia(
        id, schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request)
    )


@router.delete("/licencias/{id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_licencia(
    id: int,
    request: Request, current_user: CurrentUser,
    service: SoftwareService = Depends(get_service),
):
    await service.delete_licencia(
        id, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request)
    )


# --- LICENCIAS INSTALADAS EN UN ACTIVO ---
@router.get(
    "/activos/{activo_id}/instalaciones",
    response_model=List[InstalacionDetalleResponse],
)
async def list_instalaciones_activo(
    activo_id: _uuid.UUID,
    solo_activas: bool = True,
    service: SoftwareService = Depends(get_service),
):
    """Lista las licencias instaladas en el activo (por defecto solo activas)."""
    return await service.list_instalaciones_by_activo(activo_id, solo_activas=solo_activas)


# --- INSTALACIONES ---
@router.post(
    "/instalaciones", response_model=InstalacionResponse, status_code=201,
    dependencies=[Depends(require_operativo)],
)
@limiter.limit("30/minute")
async def registrar_instalacion(
    schema: InstalacionCreate,
    request: Request,
    current_user: CurrentUser,
    service: SoftwareService = Depends(get_service),
    idempotency: _IdempotencyGuard = Depends(idempotency_guard),
):
    """
    Asigna una licencia a un activo. Reserva el cupo atómicamente.
    Soporta cabecera 'Idempotency-Key' para evitar duplicados por reintentos.
    """
    cached = await idempotency.lookup()
    if cached is not None:
        return cached

    result = await service.registrar_instalacion(
        schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request)
    )
    await idempotency.store(result, status_code=201)
    return result


@router.post(
    "/instalaciones/desinstalar", status_code=200,
    dependencies=[Depends(require_operativo)],
)
async def desinstalar_software(
    schema: InstalacionCreate,
    request: Request,
    current_user: CurrentUser,
    service: SoftwareService = Depends(get_service),
):
    """Libera el cupo de la licencia (idempotente)."""
    return await service.desinstalar_software(
        schema, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request)
    )
