"""
Seguridad: hashing de contraseñas, emisión/validación de JWTs y cifrado de
campos sensibles (Fernet).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from cryptography.fernet import Fernet, MultiFernet, InvalidToken
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

# Hash dummy precomputado (una vez por proceso). Se usa para igualar el tiempo
# de respuesta del login cuando el usuario NO existe, cerrando el oráculo de
# timing que permitía enumerar cuentas (ver login.py::login_access_token).
_DUMMY_PASSWORD_HASH = pwd_context.hash("timing-equalization-dummy-password")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def verify_password_dummy() -> None:
    """
    Ejecuta una verificación argon2 contra un hash dummy para gastar el mismo
    tiempo de CPU que un verify real. Llamar cuando el usuario no existe, así
    el atacante no distingue 'usuario inexistente' de 'password incorrecta'
    por la latencia de la respuesta.
    """
    try:
        pwd_context.verify("timing", _DUMMY_PASSWORD_HASH)
    except Exception:
        pass


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


def create_2fa_challenge_token(username: str) -> str:
    """
    Token efímero que prueba "este usuario pasó la contraseña" entre el paso 1
    (login) y el paso 2 (verificación del 2º factor). NO sirve para acceder a la
    API; solo se acepta en /login/2fa/verify.
    """
    from jose import jwt as _jwt
    now = datetime.now(timezone.utc)
    payload = {
        "iat": now,
        "exp": now + timedelta(minutes=settings.TWO_FACTOR_CHALLENGE_EXPIRE_MINUTES),
        "sub": str(username),
        "type": "2fa",
        "jti": secrets.token_hex(16),
    }
    return _jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_2fa_challenge(token: str) -> Optional[str]:
    """Devuelve el username si el challenge es válido y del tipo correcto; si no, None."""
    from jose import jwt as _jwt, JWTError
    try:
        payload = _jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "2fa":
        return None
    return payload.get("sub")


# =========================================================================
# PASSWORD RESET TOKENS (olvidé mi contraseña)
#
# Se genera un token aleatorio de alta entropía que se ENVÍA por email al
# correo corporativo del usuario, pero en la BD solo se guarda su hash SHA-256.
# Así, una fuga de la BD no expone tokens utilizables. El token es de un solo
# uso y expira. (No lleva salt porque no es una contraseña adivinable: son 256
# bits aleatorios, inmunes a fuerza bruta / rainbow tables.)
# =========================================================================
def generate_reset_token() -> tuple[str, str]:
    """Devuelve (token_plano, token_hash). El plano va al email; el hash a la BD."""
    token = secrets.token_urlsafe(32)
    return token, hash_reset_token(token)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# =========================================================================
# 2FA / MFA — TOTP (app autenticadora) + Email-OTP + códigos de recuperación
#
# El secreto TOTP se guarda CIFRADO (Fernet) en la BD. Los códigos OTP de email
# y los de recuperación se guardan solo como hash SHA-256 (de un solo uso).
# =========================================================================
def generate_totp_secret() -> str:
    """Secreto base32 para TOTP."""
    import pyotp
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, username: str, issuer: str) -> str:
    """otpauth:// URI para que la app autenticadora lo escanee (QR)."""
    import pyotp
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    """Valida un código TOTP con tolerancia de ±1 ventana (desfase de reloj)."""
    import pyotp
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
    except Exception:  # noqa: BLE001
        return False


def generate_numeric_otp(digits: int = 6) -> str:
    """Código numérico aleatorio (para Email-OTP)."""
    return "".join(secrets.choice("0123456789") for _ in range(digits))


def generate_recovery_codes(n: int = 8) -> list[str]:
    """Códigos de recuperación legibles (xxxx-xxxx) de un solo uso."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin O/0/I/1 ambiguos
    codes = []
    for _ in range(n):
        raw = "".join(secrets.choice(alphabet) for _ in range(8))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def hash_code(code: str) -> str:
    """Hash SHA-256 para OTP de email y códigos de recuperación (normaliza may/espacios)."""
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


# =========================================================================
# FIELD ENCRYPTION (Fernet) — para LIC_Clave_Activacion u otros campos
#
# Rotación de clave: FIELD_ENCRYPTION_KEY admite una lista separada por comas.
# La PRIMERA clave es la primaria (se usa para cifrar); las siguientes son
# claves legadas que solo se intentan al descifrar. Esto permite rotar sin
# re-cifrar todo de golpe:
#   1) generar clave nueva, ponerla PRIMERA: FIELD_ENCRYPTION_KEY=nueva,vieja
#   2) (opcional) re-cifrar registros existentes en background
#   3) eliminar la clave vieja cuando ya no queden valores cifrados con ella
# =========================================================================
_fernet: Optional[MultiFernet] = None


def _get_fernet() -> Optional[MultiFernet]:
    global _fernet
    if _fernet is None and settings.FIELD_ENCRYPTION_KEY:
        keys = [k.strip() for k in settings.FIELD_ENCRYPTION_KEY.split(",") if k.strip()]
        if keys:
            _fernet = MultiFernet([Fernet(k.encode()) for k in keys])
    return _fernet


def encrypt_field(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    fernet = _get_fernet()
    if fernet is None:
        # Sin clave: avisamos UNA VEZ por proceso. El validador de config ya
        # rechaza este estado en producción (ENVIRONMENT=production).
        import structlog
        structlog.get_logger("security").warning(
            "encrypt_field.no_key — el valor se guarda en CLARO. "
            "Configura FIELD_ENCRYPTION_KEY para activar cifrado."
        )
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
        # Valor no descifrable: o es legado pre-cifrado, o fue manipulado.
        import structlog
        structlog.get_logger("security").warning(
            "decrypt_field.invalid_token — valor no descifrable; posible tampering o legado."
        )
        # En PRODUCCIÓN fallamos cerrado: no servimos un valor potencialmente
        # manipulado como si fuera legítimo. En dev/staging mantenemos la
        # tolerancia para no romper datasets legados durante una migración.
        if settings.IS_PRODUCTION:
            raise ValueError("FIELD_DECRYPT_FAILED")
        return value
