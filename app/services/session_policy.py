"""
Restricciones de sesión (claims del JWT) que obligan a completar un paso
de seguridad antes de usar el sistema:

- pwd_change: la cuenta tiene una contraseña temporal asignada por un
  administrador → debe cambiarla.
- mfa_enroll: el rol exige MFA y la cuenta no lo tiene configurado → debe
  enrolar un segundo factor.

Con cualquiera de ellas, `get_current_user` rechaza la petición (403) salvo en
los endpoints de autoservicio (/me, /me/password, /me/2fa/*). Las
restricciones se recalculan desde la BD en cada login y en cada refresh, así
que desaparecen en cuanto el usuario completa el paso.

Los inicios de sesión SSO no llevan restricciones: la contraseña y el segundo
factor los gestiona el proveedor de identidad (Entra ID / Google).
"""
from __future__ import annotations

from typing import Any

from app.services.twofactor import role_requires_2fa

PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"
MFA_ENROLLMENT_REQUIRED = "MFA_ENROLLMENT_REQUIRED"


def session_claims(user, *, via_sso: bool = False) -> dict[str, Any]:
    if via_sso:
        return {"amr": "sso"}
    claims: dict[str, Any] = {}
    if getattr(user, "USU_Debe_Cambiar_Password", False):
        claims["pwd_change"] = True
    if role_requires_2fa(user.USU_Rol) and not user.USU_2FA_Habilitado:
        claims["mfa_enroll"] = True
    return claims


def restriction_error(payload: dict) -> str | None:
    """Código del paso pendiente (la contraseña va primero), o None."""
    if payload.get("pwd_change"):
        return PASSWORD_CHANGE_REQUIRED
    if payload.get("mfa_enroll"):
        return MFA_ENROLLMENT_REQUIRED
    return None
