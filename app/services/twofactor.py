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
from app.core.errors import utcnow_naive
from app.core.transactional import schedule_post_commit, transactional
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
    @transactional
    async def totp_setup(self, user) -> dict:
        if user.USU_2FA_Habilitado:
            raise HTTPException(409, "2FA_ALREADY_ENABLED")
        secret = security.generate_totp_secret()
        # Guardar el secreto CIFRADO, pero 2FA aún no habilitado hasta activar.
        user.USU_2FA_Secret = security.encrypt_field(secret)
        user.USU_2FA_Metodo = None
        uri = security.totp_provisioning_uri(secret, user.USU_Username, settings.TWO_FACTOR_ISSUER)
        return {"secret": secret, "otpauth_uri": uri, "qr_data_uri": _qr_data_uri(uri)}

    @transactional
    async def totp_activate(self, user, code: str, ip=None) -> list[str]:
        if user.USU_2FA_Habilitado:
            raise HTTPException(409, "2FA_ALREADY_ENABLED")
        if not user.USU_2FA_Secret:
            raise HTTPException(400, "2FA_SETUP_NOT_STARTED")
        secret = security.decrypt_field(user.USU_2FA_Secret)
        if not self._accept_totp(user, secret, code):
            raise HTTPException(400, "INVALID_2FA_CODE")
        return await self._enable(user, "TOTP", ip)

    # ------------------------------------------------------------------
    # Enrolamiento EMAIL
    # ------------------------------------------------------------------
    @transactional
    async def email_setup(self, user) -> None:
        if user.USU_2FA_Habilitado:
            raise HTTPException(409, "2FA_ALREADY_ENABLED")
        await self._issue_email_otp(user)

    @transactional
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
    @transactional
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

    @transactional
    async def regenerate_recovery_codes(self, user, ip=None) -> list[str]:
        if not user.USU_2FA_Habilitado:
            raise HTTPException(400, "2FA_NOT_ENABLED")
        return await self._new_recovery_codes(user, ip, audit="2FA_RECOVERY_REGENERATED")

    # ------------------------------------------------------------------
    # Login: emitir OTP de email (método EMAIL) y verificar 2º factor
    # ------------------------------------------------------------------
    @transactional
    async def issue_email_login_otp(self, user) -> None:
        await self._issue_email_otp(user)

    @transactional
    async def verify_login(self, user, code: str) -> bool:
        """Valida el 2º factor en login: TOTP/EMAIL según método, o un código de recuperación."""
        code = (code or "").strip()
        ok = False
        if user.USU_2FA_Metodo == "TOTP":
            secret = security.decrypt_field(user.USU_2FA_Secret) if user.USU_2FA_Secret else None
            ok = self._accept_totp(user, secret, code)
        elif user.USU_2FA_Metodo == "EMAIL":
            ok = await self._check_email_otp(user, code)
        if ok:
            return True
        # Fallback: código de recuperación (un solo uso).
        if "-" in code or len(code) >= 8:
            if await self.gov_repo.consume_recovery_code(user.USU_Usuario, security.hash_code(code)):
                return True
        return False

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------
    @staticmethod
    def _accept_totp(user, secret: str | None, code: str) -> bool:
        """Valida el código y lo consume: el mismo código (o uno anterior) ya no sirve."""
        step = security.totp_matched_step(secret, code) if secret else None
        if step is None:
            return False
        if user.USU_2FA_Ultimo_Paso is not None and step <= user.USU_2FA_Ultimo_Paso:
            return False
        user.USU_2FA_Ultimo_Paso = step
        return True

    async def _enable(self, user, metodo: str, ip) -> list[str]:
        user.USU_2FA_Habilitado = True
        user.USU_2FA_Metodo = metodo
        codes = await self._new_recovery_codes(user, ip, audit=None)
        await self.gov_repo.create_audit_log(
            "2FA_ENABLED", "INV_USUARIO", {"username": user.USU_Username, "metodo": metodo},
            usuario_id=user.USU_Usuario, ip_origen=ip,
        )
        return codes

    async def _new_recovery_codes(self, user, ip, audit) -> list[str]:
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
        return plain

    async def _issue_email_otp(self, user) -> None:
        await self.gov_repo.invalidate_email_otps(user.USU_Usuario)
        code = security.generate_numeric_otp(6)
        expira = utcnow_naive() + timedelta(minutes=settings.TWO_FACTOR_EMAIL_OTP_EXPIRE_MINUTES)
        await self.gov_repo.create_email_otp(user.USU_Usuario, security.hash_code(code), expira)
        self._schedule_email_otp_notification(user, code)

    def _schedule_email_otp_notification(self, user, code: str) -> None:
        """Queue delivery only after the OTP transaction has committed."""
        per = user.persona
        context = {
            "persona_nombre": (
                f"{per.PER_Primer_Nombre} {per.PER_Primer_Apellido}"
                if per else user.USU_Username
            ),
            "username": user.USU_Username,
            "code": code,
            "minutos": settings.TWO_FACTOR_EMAIL_OTP_EXPIRE_MINUTES,
        }
        recipients = [per.PER_Email_Corporativo] if per and per.PER_Email_Corporativo else ()

        async def send() -> None:
            from app.core.email import send_notification

            await send_notification("2fa_code", context, to=recipients, cc_admins=False)

        schedule_post_commit(self, send)

    async def _check_email_otp(self, user, code: str) -> bool:
        otp = await self.gov_repo.get_active_email_otp(user.USU_Usuario)
        if not otp:
            return False
        if otp.TFC_Intentos >= settings.TWO_FACTOR_MAX_ATTEMPTS:
            await self.gov_repo.mark_email_otp_used(otp.TFC_Id)  # invalidar tras demasiados intentos
            return False
        if security.hash_code(code) == otp.TFC_Code_Hash:
            await self.gov_repo.mark_email_otp_used(otp.TFC_Id)
            return True
        await self.gov_repo.bump_email_otp_attempts(otp.TFC_Id)
        return False
