"""
Gestión de la cuenta de servicio (correo + AD) desde la UI: lectura sin
secretos, guardado auditado y pruebas con los valores del formulario.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.governance import IntegracionCorreo
from app.repositories.governance import GovernanceRepository
from app.services import integration_config as ic

_TEST_SUBJECT = "[Inventario] Prueba de la cuenta de servicio"
_TEST_HTML = """
<div style="font-family:Segoe UI,Arial,sans-serif;color:#1f2937">
  <h2>Correo de prueba</h2>
  <p>La cuenta de servicio del Sistema de Inventario TI puede enviar correos correctamente.</p>
  <p style="color:#6b7280;font-size:12px">Remitente: {remitente} · Proveedor: {proveedor}</p>
</div>
"""


def env_values() -> dict[str, Any]:
    """Valores efectivos del entorno en formato de API (incluye secretos, uso interno)."""
    cfg = ic.from_env()
    return {
        "modo": cfg.mode, "proveedor": "SMTP",
        "cuenta_email": settings.SMTP_FROM_EMAIL if cfg.mail.enabled else None,
        "cuenta_usuario": settings.SMTP_USER or None,
        "cuenta_password": settings.SMTP_PASSWORD or None,
        "nombre_remitente": settings.SMTP_FROM_NAME,
        "smtp_host": settings.SMTP_HOST, "smtp_puerto": settings.SMTP_PORT,
        "smtp_seguridad": cfg.mail.security,
        "graph_tenant_id": None, "graph_client_id": None, "graph_client_secret": None,
        "ad_servidor": settings.AD_SERVER or None, "ad_base_dn": settings.AD_BASE_DN or None,
        "ad_grupo_base_dn": settings.AD_GROUP_BASE_DN or None,
        "ad_grupo_admin": settings.AD_ADMIN_GROUP or None,
        "ad_start_tls": settings.AD_START_TLS, "ad_verificar_cert": settings.AD_VERIFY_CERT,
        "ad_intervalo_min": settings.AD_SYNC_INTERVAL_MINUTES, "ad_desactivar": settings.AD_SYNC_DEACTIVATE,
        "ad_usar_cuenta_servicio": False,
        "ad_bind_usuario": settings.AD_BIND_USER, "ad_bind_password": settings.AD_BIND_PASSWORD,
    }


class IntegrationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.gov_repo = GovernanceRepository(db)

    async def _stored(self) -> tuple[dict[str, Any], str]:
        row = await self.db.get(IntegracionCorreo, 1)
        if row is None:
            return env_values(), "entorno"
        return ic.row_to_values(row), "interfaz"

    async def get(self) -> dict[str, Any]:
        values, origen = await self._stored()
        return await self._out(values, origen)

    async def _out(self, v: dict[str, Any], origen: str) -> dict[str, Any]:
        public = {k: val for k, val in v.items() if k not in ic.SECRETS}
        smtp_hasta = await ic.breaker_until("smtp")
        ad_hasta = await ic.breaker_until("ad")
        return {
            **public,
            "smtp_puerto": public.get("smtp_puerto") or 587,
            "smtp_seguridad": public.get("smtp_seguridad") or "STARTTLS",
            "ad_intervalo_min": public.get("ad_intervalo_min") or 0,
            "origen": origen,
            "password_configurada": bool(v.get("cuenta_password")),
            "graph_secret_configurado": bool(v.get("graph_client_secret")),
            "ad_bind_password_configurada": bool(v.get("ad_bind_password")),
            "bloqueo": {
                "smtp_hasta": smtp_hasta.isoformat() if smtp_hasta else None,
                "ad_hasta": ad_hasta.isoformat() if ad_hasta else None,
            },
            "cifrado_ok": bool(settings.FIELD_ENCRYPTION_KEY),
        }

    async def save(self, data: dict[str, Any], usuario_id: uuid.UUID | None, ip: str | None) -> dict[str, Any]:
        row = await self.db.get(IntegracionCorreo, 1)
        if row is None:
            # Primer guardado desde la UI: se heredan los secretos del entorno
            # que el formulario deja "sin cambios".
            row = IntegracionCorreo(INT_Id=1)
            self.db.add(row)
            env = env_values()
            data = {**data, **{k: env[k] for k in ic.SECRETS if data.get(k) is None and env.get(k)}}
        ic.apply_values(row, data)
        row.USU_Actualizado_Por = usuario_id
        await self.db.flush()
        await self.gov_repo.create_audit_log(
            accion="UPDATE", entidad="SYS_INTEGRACION_CORREO",
            snapshot={
                **{k: v for k, v in data.items() if k not in ic.SECRETS},
                # Nunca se auditan secretos: solo si cambiaron.
                "secretos_modificados": sorted(k for k in ic.SECRETS if data.get(k) is not None),
            },
            usuario_id=usuario_id, ip_origen=ip,
        )
        await self.db.commit()
        values = ic.row_to_values(row)
        ic.set_cached_values(values)
        await ic.reset_breakers()  # credenciales nuevas: se reanudan los intentos
        return await self._out(values, "interfaz")

    async def _form_config(self, form: dict[str, Any]) -> ic.IntegrationConfig:
        stored, _ = await self._stored()
        return ic.from_values(ic.merge_with_stored(form, stored), source="prueba")

    async def test_mail(self, form: dict[str, Any], destinatario: str) -> dict[str, Any]:
        from app.core.email import MailSendError, deliver_with_config

        cfg = (await self._form_config(form)).mail
        if not cfg.ready:
            return {"ok": False, "codigo": "NOT_CONFIGURED", "mensaje": "Modo desactivado o faltan datos del proveedor."}
        try:
            await deliver_with_config(
                cfg, [destinatario], _TEST_SUBJECT,
                _TEST_HTML.format(remitente=cfg.from_email, proveedor=cfg.provider),
                use_breaker=False,
            )
        except MailSendError as e:
            return {"ok": False, "codigo": e.code, "mensaje": e.message}
        await ic.reset_breakers("smtp")
        return {"ok": True, "codigo": "OK", "mensaje": f"Correo enviado a {destinatario}"}

    async def test_ad(self, form: dict[str, Any]) -> dict[str, Any]:
        from app.integrations.active_directory import DirectoryAuthError, DirectoryError, LdapDirectoryClient

        cfg = (await self._form_config({**form, "modo": "CORREO_AD"})).ad
        if not cfg.configured:
            return {"ok": False, "codigo": "NOT_CONFIGURED", "mensaje": "Faltan servidor, base DN o usuario de conexión."}
        try:
            total = await LdapDirectoryClient(cfg, use_breaker=False).test_connection()
        except DirectoryAuthError as e:
            return {"ok": False, "codigo": "AUTH_FAILED", "mensaje": str(e)}
        except DirectoryError as e:
            return {"ok": False, "codigo": "CONNECTION_FAILED", "mensaje": str(e)}
        await ic.reset_breakers("ad")
        return {"ok": True, "codigo": "OK", "mensaje": "Conexión correcta", "usuarios_encontrados": total}
