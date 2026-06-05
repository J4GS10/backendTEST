"""
Servicio de 2FA / MFA. Soporta dos métodos:
- TOTP: app autenticadora (secreto cifrado con Fernet).
- EMAIL: código numérico enviado al correo en cada login.

Más códigos de recuperación (un solo uso) por si se pierde el 2º factor.
"""
from __future__ import annotations

import base64
import io
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.errors import internal_error, utcnow_naive
from app.core.transactional import commit_or_409
from app.repositories.governance import GovernanceRepository
from app.repositories.organization import UsuarioRepository


def role_requires_2fa(role: str) -> bool:
    required = {r.strip() for r in (settings.TWO_FACTOR_REQUIRED_ROLES or "").split(",") if r.strip()}
    return role in required


def _qr_data_uri(otpauth_uri: str) -> str:
    import qrcode
    img = qrcode.make(otpauth_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


class TwoFactorService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.usu_repo = UsuarioRepository(db)
        self.gov_repo = GovernanceRepository(db)

    def status(self, user) -> dict:
        return {
            "habilitado": bool(user.USU_2FA_Habilitado),
            "metodo": user.USU_2FA_Metodo,
            "requerido": role_requires_2fa(user.USU_Rol),
        }

    # ------------------------------------------------------------------
    # Enrolamiento TOTP
    # ------------------------------------------------------------------
    async def totp_setup(self, user) -> dict:
        if user.USU_2FA_Habilitado:
            raise HTTPException(409, "2FA_ALREADY_ENABLED")
        secret = security.generate_totp_secret()
        # Guardar el secreto CIFRADO, pero 2FA aún no habilitado hasta activar.
        user.USU_2FA_Secret = security.encrypt_field(secret)
        user.USU_2FA_Metodo = None
        await commit_or_409(self.db, where="TwoFactorService.totp_setup")
        uri = security.totp_provisioning_uri(secret, user.USU_Username, settings.TWO_FACTOR_ISSUER)
        return {"secret": secret, "otpauth_uri": uri, "qr_data_uri": _qr_data_uri(uri)}

    async def totp_activate(self, user, code: str, ip=None) -> list[str]:
        if user.USU_2FA_Habilitado:
            raise HTTPException(409, "2FA_ALREADY_ENABLED")
        if not user.USU_2FA_Secret:
            raise HTTPException(400, "2FA_SETUP_NOT_STARTED")
        secret = security.decrypt_field(user.USU_2FA_Secret)
        if not security.verify_totp(secret, code):
            raise HTTPException(400, "INVALID_2FA_CODE")
        return await self._enable(user, "TOTP", ip)

    # ------------------------------------------------------------------
    # Enrolamiento EMAIL
    # ------------------------------------------------------------------
    async def email_setup(self, user) -> None:
        if user.USU_2FA_Habilitado:
            raise HTTPException(409, "2FA_ALREADY_ENABLED")
        await self._issue_email_otp(user)

    async def email_activate(self, user, code: str, ip=None) -> list[str]:
        if user.USU_2FA_Habilitado:
            raise HTTPException(409, "2FA_ALREADY_ENABLED")
        if not await self._check_email_otp(user, code):
            raise HTTPException(400, "INVALID_2FA_CODE")
        # En método EMAIL no se persiste secreto TOTP.
        user.USU_2FA_Secret = None
        return await self._enable(user, "EMAIL", ip)

    # ------------------------------------------------------------------
    # Desactivar
    # ------------------------------------------------------------------
    async def disable(self, user, password: str, ip=None) -> None:
        if not security.verify_password(password, user.USU_Password_Hash):
            raise HTTPException(400, "INCORRECT_CURRENT_PASSWORD")
        if not user.USU_2FA_Habilitado:
            return
        if role_requires_2fa(user.USU_Rol):
            raise HTTPException(403, "2FA_REQUIRED_FOR_THIS_ROLE")
        user.USU_2FA_Habilitado = False
        user.USU_2FA_Metodo = None
        user.USU_2FA_Secret = None
        await self.gov_repo.delete_recovery_codes(user.USU_Usuario)
        await self.gov_repo.invalidate_email_otps(user.USU_Usuario)
        await self.gov_repo.create_audit_log(
            "2FA_DISABLED", "INV_USUARIO", {"username": user.USU_Username},
            usuario_id=user.USU_Usuario, ip_origen=ip,
        )
        await commit_or_409(self.db, where="TwoFactorService.disable")

    async def regenerate_recovery_codes(self, user, ip=None) -> list[str]:
        if not user.USU_2FA_Habilitado:
            raise HTTPException(400, "2FA_NOT_ENABLED")
        return await self._new_recovery_codes(user, ip, audit="2FA_RECOVERY_REGENERATED")

    # ------------------------------------------------------------------
    # Login: emitir OTP de email (método EMAIL) y verificar 2º factor
    # ------------------------------------------------------------------
    async def issue_email_login_otp(self, user) -> None:
        await self._issue_email_otp(user)

    async def verify_login(self, user, code: str) -> bool:
        """Valida el 2º factor en login: TOTP/EMAIL según método, o un código de recuperación."""
        code = (code or "").strip()
        ok = False
        if user.USU_2FA_Metodo == "TOTP":
            secret = security.decrypt_field(user.USU_2FA_Secret) if user.USU_2FA_Secret else None
            ok = security.verify_totp(secret, code)
        elif user.USU_2FA_Metodo == "EMAIL":
            ok = await self._check_email_otp(user, code)
        if ok:
            return True
        # Fallback: código de recuperación (un solo uso).
        if "-" in code or len(code) >= 8:
            if await self.gov_repo.consume_recovery_code(user.USU_Usuario, security.hash_code(code)):
                await self.db.commit()
                return True
        return False

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------
    async def _enable(self, user, metodo: str, ip) -> list[str]:
        try:
            user.USU_2FA_Habilitado = True
            user.USU_2FA_Metodo = metodo
            codes = await self._new_recovery_codes(user, ip, audit=None, commit=False)
            await self.gov_repo.create_audit_log(
                "2FA_ENABLED", "INV_USUARIO", {"username": user.USU_Username, "metodo": metodo},
                usuario_id=user.USU_Usuario, ip_origen=ip,
            )
            await self.db.commit()
            return codes
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def _new_recovery_codes(self, user, ip, audit, commit=True) -> list[str]:
        plain = security.generate_recovery_codes(settings.TWO_FACTOR_RECOVERY_CODES)
        await self.gov_repo.delete_recovery_codes(user.USU_Usuario)
        await self.gov_repo.create_recovery_codes(
            user.USU_Usuario, [security.hash_code(c) for c in plain]
        )
        if audit:
            await self.gov_repo.create_audit_log(
                audit, "INV_USUARIO", {"username": user.USU_Username},
                usuario_id=user.USU_Usuario, ip_origen=ip,
            )
        if commit:
            await commit_or_409(self.db, where="TwoFactorService._new_recovery_codes")
        return plain

    async def _issue_email_otp(self, user) -> None:
        await self.gov_repo.invalidate_email_otps(user.USU_Usuario)
        code = security.generate_numeric_otp(6)
        expira = utcnow_naive() + timedelta(minutes=settings.TWO_FACTOR_EMAIL_OTP_EXPIRE_MINUTES)
        await self.gov_repo.create_email_otp(user.USU_Usuario, security.hash_code(code), expira)
        await commit_or_409(self.db, where="TwoFactorService._issue_email_otp")
        # Email post-commit fire-and-forget, SOLO al correo del usuario.
        try:
            from app.core.email import send_notification
            per = user.persona
            await send_notification(
                "2fa_code",
                {
                    "persona_nombre": (f"{per.PER_Primer_Nombre} {per.PER_Primer_Apellido}" if per else user.USU_Username),
                    "username": user.USU_Username,
                    "code": code,
                    "minutos": settings.TWO_FACTOR_EMAIL_OTP_EXPIRE_MINUTES,
                },
                to=[per.PER_Email_Corporativo] if per and per.PER_Email_Corporativo else (),
                cc_admins=False,
            )
        except Exception:  # noqa: BLE001
            pass

    async def _check_email_otp(self, user, code: str) -> bool:
        otp = await self.gov_repo.get_active_email_otp(user.USU_Usuario)
        if not otp:
            return False
        if otp.TFC_Intentos >= settings.TWO_FACTOR_MAX_ATTEMPTS:
            await self.gov_repo.mark_email_otp_used(otp.TFC_Id)  # invalidar tras demasiados intentos
            await self.db.commit()
            return False
        if security.hash_code(code) == otp.TFC_Code_Hash:
            await self.gov_repo.mark_email_otp_used(otp.TFC_Id)
            await self.db.commit()
            return True
        await self.gov_repo.bump_email_otp_attempts(otp.TFC_Id)
        await self.db.commit()
        return False
