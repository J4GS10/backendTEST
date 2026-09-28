"""Active Directory (estado, prueba, sincronización, grupos) y reglas de notificación."""
from dataclasses import asdict
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_client_ip, require_admin, require_super_admin
from app.core.limiter import limiter
from app.db.session import get_db
from app.integrations.active_directory import DirectoryError, get_directory_client
from app.schemas.directory import (
    ConnectionTest, DirectoryStatus, GroupOut, IntegracionOut, IntegracionUpdate, ProbarAdIn,
    ProbarCorreoIn, ReglaOut, ReglaUpdate, ResultadoPrueba, SyncResult, VistaPrevia,
)
from app.services import integration_config
from app.services.integration_service import IntegrationService
from app.services.directory_sync import DirectorySyncService
from app.services.notification_rules import NotificationRulesService

router = APIRouter()

ADMIN = [Depends(require_admin)]
SUPER = [Depends(require_super_admin)]


# ================= ACTIVE DIRECTORY =================
@router.get("/estado", response_model=DirectoryStatus, dependencies=ADMIN)
async def estado(db: AsyncSession = Depends(get_db)):
    ad = (await integration_config.get_config(db)).ad
    return DirectoryStatus(
        enabled=ad.enabled,
        configured=ad.configured,
        server=",".join(ad.servers) or None,
        base_dn=ad.base_dn or None,
        admin_group=ad.admin_group or None,
        sync_interval_minutes=ad.sync_interval_min,
        last_sync=await DirectorySyncService(db).last_sync(),
    )


@router.post("/probar", response_model=ConnectionTest, dependencies=SUPER)
@limiter.limit("10/minute")
async def probar(request: Request, db: AsyncSession = Depends(get_db)):
    client = await get_directory_client(db)
    if client is None:
        return ConnectionTest(ok=False, message="AD_DISABLED")
    try:
        total = await client.test_connection()
    except DirectoryError as e:
        return ConnectionTest(ok=False, message=str(e))
    return ConnectionTest(ok=True, message="OK", usuarios_encontrados=total)


@router.post("/sincronizar", response_model=SyncResult, dependencies=ADMIN)
@limiter.limit("6/minute")
async def sincronizar(
    request: Request, current_user: CurrentUser,
    dry_run: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    return await DirectorySyncService(db).sync(
        dry_run=dry_run, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request),
    )


@router.get("/grupos", response_model=list[GroupOut], dependencies=SUPER)
async def grupos(q: str = Query("", max_length=100), db: AsyncSession = Depends(get_db)):
    client = await get_directory_client(db)
    if client is None:
        return []
    try:
        return [GroupOut(nombre=g.nombre, dn=g.dn) for g in await client.search_groups(q)]
    except DirectoryError:
        return []


# ================= CUENTA DE SERVICIO (CORREO + AD) =================
@router.get("/integracion", response_model=IntegracionOut, dependencies=SUPER)
async def get_integracion(db: AsyncSession = Depends(get_db)):
    """Configuración de la cuenta de servicio. Nunca devuelve secretos."""
    return await IntegrationService(db).get()


@router.put("/integracion", response_model=IntegracionOut, dependencies=SUPER)
async def put_integracion(
    schema: IntegracionUpdate, request: Request, current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    return await IntegrationService(db).save(
        schema.model_dump(mode="json"), usuario_id=current_user.USU_Usuario, ip=get_client_ip(request),
    )


@router.post("/integracion/probar-correo", response_model=ResultadoPrueba, dependencies=SUPER)
@limiter.limit("5/minute")
async def probar_correo(request: Request, body: ProbarCorreoIn, db: AsyncSession = Depends(get_db)):
    """Envía un correo real con los valores del formulario (sin guardarlos)."""
    return await IntegrationService(db).test_mail(body.config.model_dump(mode="json"), str(body.destinatario))


@router.post("/integracion/probar-ad", response_model=ResultadoPrueba, dependencies=SUPER)
@limiter.limit("5/minute")
async def probar_ad(request: Request, body: ProbarAdIn, db: AsyncSession = Depends(get_db)):
    """Bind + búsqueda de usuarios con los valores del formulario (sin guardarlos)."""
    return await IntegrationService(db).test_ad(body.config.model_dump(mode="json"))


@router.post("/integracion/desbloquear", status_code=204, dependencies=SUPER)
async def desbloquear():
    """Reanuda envíos/consultas pausados por un fallo de autenticación."""
    await integration_config.reset_breakers()
    return Response(status_code=204)


# ================= REGLAS DE NOTIFICACIÓN =================
@router.get("/notificaciones/reglas", response_model=list[ReglaOut], dependencies=SUPER)
async def list_reglas(db: AsyncSession = Depends(get_db)):
    return [asdict(r) for r in await NotificationRulesService(db).list_rules()]


@router.put("/notificaciones/reglas/{evento}", response_model=ReglaOut, dependencies=SUPER)
async def update_regla(
    evento: str, schema: ReglaUpdate, request: Request, current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    rule = await NotificationRulesService(db).upsert_rule(
        evento, schema.model_dump(mode="json"),
        usuario_id=current_user.USU_Usuario, ip=get_client_ip(request),
    )
    return asdict(rule)


@router.delete("/notificaciones/reglas/{evento}", status_code=204, dependencies=SUPER)
async def reset_regla(
    evento: str, request: Request, current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await NotificationRulesService(db).reset_rule(
        evento, usuario_id=current_user.USU_Usuario, ip=get_client_ip(request),
    )
    return Response(status_code=204)


@router.get("/notificaciones/vista-previa/{evento}", response_model=VistaPrevia, dependencies=SUPER)
async def vista_previa(
    evento: str, persona_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
):
    pairs = await NotificationRulesService(db).preview(evento, persona_id)
    return VistaPrevia(
        destinatarios=[e for e, _ in pairs],
        detalle=[{"email": e, "origen": o} for e, o in pairs],
    )
