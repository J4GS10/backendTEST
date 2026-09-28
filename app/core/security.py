"""
Seguridad: hashing de contraseñas, emisión/validación de JWTs y cifrado de
campos sensibles (Fernet).
"""
from __future__ import annotations

import hashlib
import hmac
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


def _strip_affixes(value: str) -> str:
    """'Verano2026!' -> 'verano': quita dígitos/símbolos al inicio y al final."""
    start, end = 0, len(value)
    while start < end and not value[start].isalpha():
        start += 1
    while end > start and not value[end - 1].isalpha():
        end -= 1
    return value[start:end]


def _deleet(value: str) -> str:
    """Revierte sustituciones típicas (p@ssw0rd -> password)."""
    return value.translate(str.maketrans({"@": "a", "4": "a", "3": "e", "1": "i", "!": "i",
                                          "0": "o", "$": "s", "5": "s", "7": "t"}))


def _has_sequence(value: str, length: int = 4) -> bool:
    from app.core.common_passwords import KEYBOARD_SEQUENCES
    low = value.lower()
    for i in range(len(low) - length + 1):
        chunk = low[i:i + length]
        if any(chunk in seq for seq in KEYBOARD_SEQUENCES):
            return True
    return False


def _has_repetition(value: str, length: int = 4) -> bool:
    return any(value[i] * length == value[i:i + length] for i in range(len(value) - length + 1))


def validate_password_policy(
    password: str, username: str | None = None, personal_data: list[str] | None = None,
) -> None:
    """
    Aplica la política configurada. Lanza PasswordPolicyError con detalle.

    `personal_data`: nombres, apellidos y parte local del correo del titular;
    la contraseña no puede contenerlos.
    """
    from app.core.common_passwords import COMMON_PASSWORDS

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

    low = password.lower()
    candidates = {low, _strip_affixes(low), _deleet(low), _strip_affixes(_deleet(low))}
    if any(c in COMMON_PASSWORDS for c in candidates if c):
        errors.append("too_common")
    if username and len(username) >= 3 and username.lower() in low:
        errors.append("contains_username")
    blocked = [w.strip().lower() for w in (settings.PASSWORD_BLOCKED_WORDS or "").split(",") if len(w.strip()) >= 4]
    if any(w in low or w in _deleet(low) for w in blocked):
        errors.append("contains_blocked_word")
    personal = [p.strip().lower() for p in (personal_data or []) if p and len(p.strip()) >= 4]
    if any(p in low or p in _deleet(low) for p in personal):
        errors.append("contains_personal_data")
    if _has_repetition(password):
        errors.append("repeated_chars")
    if _has_sequence(password):
        errors.append("sequential_chars")

    if errors:
        raise PasswordPolicyError(
            "PASSWORD_POLICY_VIOLATION:" + ",".join(errors)
        )


def generate_temporary_password(username: str | None = None, length: int = 16) -> str:
    """
    Contraseña temporal aleatoria (CSPRNG) que cumple la política vigente:
    incluye mayúscula, minúscula, dígito y símbolo, sin caracteres ambiguos
    (0/O, 1/l/I) para que el administrador pueda dictarla sin errores.
    """
    upper, lower, digits, symbols = "ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnopqrstuvwxyz", "23456789", "#$%&*+-=?@"
    alphabet = upper + lower + digits + symbols
    length = max(length, settings.PASSWORD_MIN_LENGTH, 12)
    while True:
        chars = [secrets.choice(upper), secrets.choice(lower), secrets.choice(digits), secrets.choice(symbols)]
        chars += [secrets.choice(alphabet) for _ in range(length - len(chars))]
        secrets.SystemRandom().shuffle(chars)
        candidate = "".join(chars)
        try:
            validate_password_policy(candidate, username=username)
            return candidate
        except PasswordPolicyError:
            continue


# =========================================================================
# JWT
# =========================================================================
TokenType = Literal["access", "refresh"]


def _create_token(
    subject: str | Any,
    role: str,
    token_type: TokenType,
    expires_delta: timedelta,
    extra: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    to_encode = {
        **(extra or {}),
        "iat": now,
        # iat del JWT es entero (segundos). iat_ms permite comparar con precisión
        # contra una revocación global ocurrida en el mismo segundo.
        "iat_ms": int(now.timestamp() * 1000),
        "exp": now + expires_delta,
        "sub": str(subject),
        "role": role,
        "type": token_type,
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def token_issued_at(payload: dict) -> datetime | None:
    """Instante de emisión (naive UTC) con precisión de ms si el token la trae."""
    if payload.get("iat_ms"):
        return datetime.fromtimestamp(payload["iat_ms"] / 1000, tz=timezone.utc).replace(tzinfo=None)
    if payload.get("iat"):
        return datetime.fromtimestamp(payload["iat"], tz=timezone.utc).replace(tzinfo=None)
    return None


def create_access_token(
    subject: str | Any, role: str, expires_delta: Optional[timedelta] = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """`extra`: restricciones de sesión (ver app/services/session_policy.py)."""
    delta = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _create_token(subject, role, "access", delta, extra=extra)


def create_refresh_token(
    subject: str | Any, role: str, auth_time: int | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """
    `auth_time` (epoch s) = momento del login original. Se conserva al rotar,
    para aplicar SESSION_ABSOLUTE_MAX_HOURS. El refresh nunca vive más allá
    de ese límite absoluto.
    """
    now = int(datetime.now(timezone.utc).timestamp())
    auth_time = auth_time or now
    session_end = auth_time + settings.SESSION_ABSOLUTE_MAX_HOURS * 3600
    delta = timedelta(seconds=max(0, min(
        settings.SESSION_IDLE_TIMEOUT_MINUTES * 60,   # inactividad (se renueva al rotar)
        settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,   # tope de vida del token
        session_end - now,                            # tope absoluto de la sesión
    )))
    return _create_token(subject, role, "refresh", delta, extra={**(extra or {}), "auth_time": auth_time})


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


def totp_matched_step(secret: str, code: str) -> int | None:
    """
    Paso temporal (contador de 30 s) al que corresponde el código, con
    tolerancia de ±1 ventana por desfase de reloj; None si no es válido.
    Permite rechazar la REUTILIZACIÓN de un código ya aceptado (replay).
    """
    import time
    import pyotp
    code = (code or "").strip()
    if not secret or not code.isdigit():
        return None
    try:
        totp = pyotp.TOTP(secret)
        now_step = int(time.time()) // totp.interval
        for step in (now_step - 1, now_step, now_step + 1):
            if hmac.compare_digest(totp.generate_otp(step), code):
                return step
    except Exception:  # noqa: BLE001
        return None
    return None


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
            "Configure FIELD_ENCRYPTION_KEY para activar cifrado."
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


def fingerprint_field(value: str) -> str:
    """
    Huella deterministica para campos sensibles cifrados.

    Fernet es no deterministico, por diseno, asi que no sirve para detectar
    duplicados. Esta huella usa HMAC-SHA256 con SECRET_KEY: permite imponer
    unicidad sin guardar el dato sensible en claro ni como hash sin clave.
    """
    normalized = (value or "").strip().encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), normalized, hashlib.sha256).hexdigest()
