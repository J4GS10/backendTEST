"""
Seguridad: hashing de contraseñas, emisión/validación de JWTs y cifrado de
campos sensibles (Fernet).
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from cryptography.fernet import Fernet, InvalidToken
from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings


# =========================================================================
# PASSWORDS
# =========================================================================
pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated="auto",
    argon2__rounds=3,
    argon2__memory_cost=65536,
    argon2__parallelism=2,
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def needs_password_rehash(hashed_password: str) -> bool:
    return pwd_context.needs_update(hashed_password)


# =========================================================================
# PASSWORD POLICY
# =========================================================================
class PasswordPolicyError(ValueError):
    """Se lanza cuando la contraseña no cumple la política."""


def validate_password_policy(password: str, username: str | None = None) -> None:
    """
    Aplica la política configurada. Lanza PasswordPolicyError con detalle.
    """
    errors = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        errors.append(f"min_length:{settings.PASSWORD_MIN_LENGTH}")
    if settings.PASSWORD_REQUIRE_UPPER and not any(c.isupper() for c in password):
        errors.append("require_upper")
    if settings.PASSWORD_REQUIRE_LOWER and not any(c.islower() for c in password):
        errors.append("require_lower")
    if settings.PASSWORD_REQUIRE_DIGIT and not any(c.isdigit() for c in password):
        errors.append("require_digit")
    if settings.PASSWORD_REQUIRE_SYMBOL and not any(
        not c.isalnum() for c in password
    ):
        errors.append("require_symbol")

    # Anti-patterns triviales
    common_bad = {"password", "12345678", "qwerty", "admin", "letmein"}
    if password.lower() in common_bad:
        errors.append("too_common")
    if username and username.lower() in password.lower():
        errors.append("contains_username")

    if errors:
        raise PasswordPolicyError(
            "PASSWORD_POLICY_VIOLATION:" + ",".join(errors)
        )


# =========================================================================
# JWT
# =========================================================================
TokenType = Literal["access", "refresh"]


def _create_token(
    subject: str | Any,
    role: str,
    token_type: TokenType,
    expires_delta: timedelta,
) -> str:
    now = datetime.now(timezone.utc)
    to_encode = {
        "iat": now,
        "exp": now + expires_delta,
        "sub": str(subject),
        "role": role,
        "type": token_type,
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(
    subject: str | Any, role: str, expires_delta: Optional[timedelta] = None
) -> str:
    delta = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _create_token(subject, role, "access", delta)


def create_refresh_token(subject: str | Any, role: str) -> str:
    delta = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return _create_token(subject, role, "refresh", delta)


# =========================================================================
# FIELD ENCRYPTION (Fernet) — para LIC_Clave_Activacion u otros campos
# =========================================================================
_fernet: Optional[Fernet] = None


def _get_fernet() -> Optional[Fernet]:
    global _fernet
    if _fernet is None and settings.FIELD_ENCRYPTION_KEY:
        _fernet = Fernet(settings.FIELD_ENCRYPTION_KEY.encode())
    return _fernet


def encrypt_field(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    fernet = _get_fernet()
    if fernet is None:
        # Sin clave configurada, no ciframos (modo dev) pero avisamos.
        return value
    return fernet.encrypt(value.encode()).decode()


def decrypt_field(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    fernet = _get_fernet()
    if fernet is None:
        return value
    try:
        return fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        # Probablemente el valor no estaba cifrado (legado).
        return value
