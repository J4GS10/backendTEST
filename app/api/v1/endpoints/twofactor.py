"""Gestión de 2FA del usuario autenticado: enrolamiento TOTP/Email, desactivar, recovery."""
from fastapi import APIRouter, Body, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_client_ip
from app.core.limiter import limiter
from app.db.session import get_db
from app.schemas.twofactor import (
    RecoveryCodesResponse, TotpSetupResponse, TwoFactorActivate, TwoFactorDisable, TwoFactorStatus,
)
from app.services.twofactor import TwoFactorService

router = APIRouter()


def get_service(db: AsyncSession = Depends(get_db)) -> TwoFactorService:
    return TwoFactorService(db)


@router.get("/me/2fa", response_model=TwoFactorStatus)
async def get_2fa_status(current_user: CurrentUser, service: TwoFactorService = Depends(get_service)):
    return service.status(current_user)


@router.post("/me/2fa/totp/setup", response_model=TotpSetupResponse)
@limiter.limit("10/minute")
async def totp_setup(request: Request, current_user: CurrentUser, service: TwoFactorService = Depends(get_service)):
    """Genera el secreto TOTP y el QR para enrolar la app autenticadora."""
    return await service.totp_setup(current_user)


@router.post("/me/2fa/totp/activate", response_model=RecoveryCodesResponse)
@limiter.limit("10/minute")
async def totp_activate(
    request: Request, current_user: CurrentUser, schema: TwoFactorActivate,
    service: TwoFactorService = Depends(get_service),
):
    """Confirma el código de la app y activa 2FA TOTP. Devuelve los códigos de recuperación (una sola vez)."""
    codes = await service.totp_activate(current_user, schema.code, ip=get_client_ip(request))
    return {"recovery_codes": codes}


@router.post("/me/2fa/email/setup", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
async def email_setup(request: Request, current_user: CurrentUser, service: TwoFactorService = Depends(get_service)):
    """Envía un código de prueba al correo del usuario para enrolar el método EMAIL."""
    await service.email_setup(current_user)
    return {"message": "Código enviado al correo registrado."}


@router.post("/me/2fa/email/activate", response_model=RecoveryCodesResponse)
@limiter.limit("10/minute")
async def email_activate(
    request: Request, current_user: CurrentUser, schema: TwoFactorActivate,
    service: TwoFactorService = Depends(get_service),
):
    codes = await service.email_activate(current_user, schema.code, ip=get_client_ip(request))
    return {"recovery_codes": codes}


@router.post("/me/2fa/disable", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def disable_2fa(
    request: Request, current_user: CurrentUser, schema: TwoFactorDisable,
    service: TwoFactorService = Depends(get_service),
):
    """Desactiva 2FA (requiere contraseña). Bloqueado si el rol obliga a tener 2FA."""
    await service.disable(current_user, schema.password, ip=get_client_ip(request))


@router.post("/me/2fa/recovery-codes/regenerate", response_model=RecoveryCodesResponse)
@limiter.limit("5/minute")
async def regenerate_recovery_codes(
    request: Request, current_user: CurrentUser, service: TwoFactorService = Depends(get_service),
):
    codes = await service.regenerate_recovery_codes(current_user, ip=get_client_ip(request))
    return {"recovery_codes": codes}
