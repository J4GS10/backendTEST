from typing import List, Optional
from pydantic import BaseModel, Field


class TwoFactorStatus(BaseModel):
    habilitado: bool
    metodo: Optional[str] = None          # 'TOTP' | 'EMAIL'
    requerido: bool = False               # si el rol del usuario obliga a tener 2FA


class TotpSetupResponse(BaseModel):
    secret: str                           # para entrada manual en la app
    otpauth_uri: str                      # otpauth://...
    qr_data_uri: str                      # data:image/png;base64,... (para <img>)


class TwoFactorActivate(BaseModel):
    code: str = Field(..., min_length=4, max_length=10)


class RecoveryCodesResponse(BaseModel):
    recovery_codes: List[str]


class TwoFactorDisable(BaseModel):
    password: str = Field(..., min_length=1)


class TwoFactorVerify(BaseModel):
    challenge_token: str = Field(..., min_length=10)
    code: str = Field(..., min_length=4, max_length=20)


class LoginChallengeResponse(BaseModel):
    requires_2fa: bool = True
    method: str
    challenge_token: str
