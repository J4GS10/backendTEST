"""
Servicio de notificaciones por email.

Diseño:
- SMTP estándar vía aiosmtplib (async). Compatible con cualquier proveedor:
  Brevo, SendGrid, Resend, MailerSend, Gmail, Mailtrap, MailHog.
- Si SMTP_HOST está vacío o EMAIL_ENABLED=False, los emails se loguean pero
  NO se envían (modo silencioso para tests / kill switch operacional).
- El envío se hace en background con FastAPI BackgroundTasks: el fallo del
  servidor SMTP NUNCA bloquea ni revierte la operación de negocio.
- Templates HTML simples vía Jinja2 (sin dependencia de carga de archivos
  en runtime: están inline en este módulo para evitar acoplamiento con
  el filesystem).
"""
from __future__ import annotations

import asyncio
from email.message import EmailMessage
from typing import Any, Iterable

import structlog
from jinja2 import Environment, BaseLoader
from markupsafe import Markup

from app.core.config import settings

log = structlog.get_logger("email")
_delivery_metrics: dict[str, Any] = {
    "sent_total": 0,
    "failed_total": 0,
    "last_delivery_ok": None,
    "last_error_type": None,
}


def email_delivery_metrics() -> dict[str, Any]:
    """Estado observable por worker; no realiza conexiones SMTP activas."""
    from app.services.integration_config import peek_config
    configured = peek_config().mail.ready
    if not configured:
        status = "disabled"
    elif _delivery_metrics["last_delivery_ok"] is True:
        status = "ok"
    elif _delivery_metrics["last_delivery_ok"] is False:
        status = "down"
    else:
        status = "unknown"
    return {
        "configured": configured,
        "status": status,
        **_delivery_metrics,
    }


# =========================================================================
# TEMPLATES — HTML simple, neutro, accesible (compatible Gmail/Outlook).
# =========================================================================
_BASE_STYLE = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         color: #1f2937; background: #f9fafb; margin:0; padding:24px; }
  .card { max-width: 560px; margin: 0 auto; background:#fff;
          border:1px solid #e5e7eb; border-radius:8px; padding:24px; }
  h1 { font-size:18px; margin:0 0 12px 0; color:#0f172a; }
  table { width:100%; border-collapse:collapse; margin-top:12px; }
  td { padding:6px 0; font-size:14px; border-bottom:1px solid #f3f4f6; }
  td.k { color:#6b7280; width:160px; }
  td.v { color:#111827; font-weight:600; }
  .footer { color:#9ca3af; font-size:12px; margin-top:24px; text-align:center; }
  .tag { display:inline-block; padding:2px 8px; border-radius:4px;
         background:#dbeafe; color:#1e40af; font-size:12px; font-weight:600; }
  .operator { margin-top:16px; padding:12px; background:#f9fafb;
              border-left:3px solid #0ea5e9; font-size:13px; color:#374151; }
  .operator b { color:#0f172a; }
</style>
"""

# Bloque común "Ejecutado por: X (rol)" — incluido en cada template via Jinja
_OPERATOR_BLOCK = """
{% if operator_name and operator_name != 'Sistema' %}
<div class="operator">
  <b>Ejecutado por:</b> {{ operator_name }}{% if operator_role %} <em>({{ operator_role }})</em>{% endif %}
  {% if reply_to %}<br><b>Contacto:</b> <a href="mailto:{{ reply_to }}">{{ reply_to }}</a>{% endif %}
</div>
{% endif %}
"""

_TEMPLATES: dict[str, str] = {
    "asignacion": """
{{ style }}
<div class="card">
  <h1>Activo asignado <span class="tag">{{ codigo }}</span></h1>
  <p>Hola {{ persona_nombre }},</p>
  <p>Se ha registrado la asignación de un activo bajo su custodia.</p>
  <table>
    <tr><td class="k">Código interno</td><td class="v">{{ codigo }}</td></tr>
    <tr><td class="k">Serie</td><td class="v">{{ serie }}</td></tr>
    <tr><td class="k">Tipo</td><td class="v">{{ tipo }}</td></tr>
    <tr><td class="k">Marca / Modelo</td><td class="v">{{ marca }} {{ modelo }}</td></tr>
    {% if hostname %}<tr><td class="k">Hostname</td><td class="v">{{ hostname }}</td></tr>{% endif %}
    <tr><td class="k">Fecha asignación</td><td class="v">{{ fecha }}</td></tr>
    <tr><td class="k">Área</td><td class="v">{{ area }}</td></tr>
    {% if observacion %}<tr><td class="k">Observación</td><td class="v">{{ observacion }}</td></tr>{% endif %}
  </table>
  <p style="margin-top:16px;font-size:13px;color:#6b7280;">
    Si recibe este activo en mano, le recomendamos conservar esta notificación como respaldo.
    Para devolverlo, comuníquese con el equipo de TI.
  </p>
  {{ operator_block }}
  <div class="footer">Sistema Inventario Lombardi · notificación automática</div>
</div>
""",
    "devolucion": """
{{ style }}
<div class="card">
  <h1>Activo devuelto <span class="tag">{{ codigo }}</span></h1>
  <p>Se ha registrado la devolución del siguiente activo:</p>
  <table>
    <tr><td class="k">Código interno</td><td class="v">{{ codigo }}</td></tr>
    <tr><td class="k">Devuelto por</td><td class="v">{{ persona_nombre }}</td></tr>
    <tr><td class="k">Fecha</td><td class="v">{{ fecha }}</td></tr>
    <tr><td class="k">Estado actual</td><td class="v">En Bodega</td></tr>
  </table>
  {{ operator_block }}
  <div class="footer">Sistema Inventario Lombardi · notificación automática</div>
</div>
""",
    "transferencia": """
{{ style }}
<div class="card">
  <h1>Transferencia de activo <span class="tag">{{ codigo }}</span></h1>
  <p>Se ha registrado una transferencia de custodia:</p>
  <table>
    <tr><td class="k">Código interno</td><td class="v">{{ codigo }}</td></tr>
    <tr><td class="k">De</td><td class="v">{{ origen_nombre }}</td></tr>
    <tr><td class="k">Hacia</td><td class="v">{{ destino_nombre }}</td></tr>
    <tr><td class="k">Fecha</td><td class="v">{{ fecha }}</td></tr>
  </table>
  {{ operator_block }}
  <div class="footer">Sistema Inventario Lombardi · notificación automática</div>
</div>
""",
    "baja": """
{{ style }}
<div class="card">
  <h1>Activo dado de baja <span class="tag">{{ codigo }}</span></h1>
  <p>El siguiente activo ha sido dado de baja del inventario:</p>
  <table>
    <tr><td class="k">Código interno</td><td class="v">{{ codigo }}</td></tr>
    <tr><td class="k">Serie</td><td class="v">{{ serie }}</td></tr>
    <tr><td class="k">Fecha de baja</td><td class="v">{{ fecha }}</td></tr>
    {% if motivo %}<tr><td class="k">Motivo</td><td class="v">{{ motivo }}</td></tr>{% endif %}
  </table>
  {{ operator_block }}
  <div class="footer">Sistema Inventario Lombardi · notificación automática</div>
</div>
""",
    "offboarding": """
{{ style }}
<div class="card">
  <h1>Salida de empleado <span class="tag">{{ persona_nombre }}</span></h1>
  <p>Se ha procesado la salida del empleado:</p>
  <table>
    <tr><td class="k">Empleado</td><td class="v">{{ persona_nombre }}</td></tr>
    <tr><td class="k">Email</td><td class="v">{{ persona_email }}</td></tr>
    <tr><td class="k">Activos devueltos</td><td class="v">{{ num_activos }}</td></tr>
    <tr><td class="k">Usuario desactivado</td><td class="v">{{ usuario_desactivado }}</td></tr>
    <tr><td class="k">Fecha</td><td class="v">{{ fecha }}</td></tr>
  </table>
  {% if activos_lista %}
  <p style="margin-top:12px;font-size:13px;"><strong>Activos liberados:</strong></p>
  <ul style="font-size:13px;color:#374151;">{% for a in activos_lista %}<li>{{ a }}</li>{% endfor %}</ul>
  {% endif %}
  {{ operator_block }}
  <div class="footer">Sistema Inventario Lombardi · notificación automática</div>
</div>
""",
    "mantenimiento_abierto": """
{{ style }}
<div class="card">
  <h1>Ticket de mantenimiento abierto <span class="tag">{{ codigo }}</span></h1>
  <p>Se ha abierto un ticket de mantenimiento:</p>
  <table>
    <tr><td class="k">Activo</td><td class="v">{{ codigo }}</td></tr>
    <tr><td class="k">Tipo</td><td class="v">{{ tipo }}</td></tr>
    <tr><td class="k">Solicita</td><td class="v">{{ persona_nombre }}</td></tr>
    <tr><td class="k">Descripción</td><td class="v">{{ descripcion }}</td></tr>
    <tr><td class="k">Fecha</td><td class="v">{{ fecha }}</td></tr>
  </table>
  {{ operator_block }}
  <div class="footer">Sistema Inventario Lombardi · notificación automática</div>
</div>
""",
    "mantenimiento_cerrado": """
{{ style }}
<div class="card">
  <h1>Mantenimiento cerrado <span class="tag">{{ codigo }}</span></h1>
  <p>El ticket de mantenimiento ha sido cerrado:</p>
  <table>
    <tr><td class="k">Activo</td><td class="v">{{ codigo }}</td></tr>
    <tr><td class="k">Costo total</td><td class="v">{{ costo }}</td></tr>
    <tr><td class="k">Fecha cierre</td><td class="v">{{ fecha }}</td></tr>
    <tr><td class="k">Estado actual</td><td class="v">{{ estado_final }}</td></tr>
  </table>
  {{ operator_block }}
  <div class="footer">Sistema Inventario Lombardi · notificación automática</div>
</div>
""",
    "stock_bajo": """
{{ style }}
<div class="card">
  <h1>Stock bajo <span class="tag">{{ codigo }}</span></h1>
  <p>El siguiente consumible alcanzó o cayó por debajo de su stock mínimo y
     conviene reabastecerlo:</p>
  <table>
    <tr><td class="k">Consumible</td><td class="v">{{ codigo }}</td></tr>
    <tr><td class="k">Stock actual</td><td class="v">{{ stock_actual }} {{ unidad }}</td></tr>
    <tr><td class="k">Stock mínimo</td><td class="v">{{ stock_minimo }} {{ unidad }}</td></tr>
    {% if categoria %}<tr><td class="k">Categoría</td><td class="v">{{ categoria }}</td></tr>{% endif %}
  </table>
  {{ operator_block }}
  <div class="footer">Sistema Inventario Lombardi · alerta automática de inventario</div>
</div>
""",
    "password_changed": """
{{ style }}
<div class="card">
  <h1>Su contraseña fue cambiada</h1>
  <p>Hola {{ persona_nombre }},</p>
  <p>Le confirmamos que la contraseña de su cuenta <b>{{ username }}</b> se cambió
     correctamente.</p>
  <table>
    <tr><td class="k">Cuenta</td><td class="v">{{ username }}</td></tr>
    <tr><td class="k">Método</td><td class="v">{{ metodo }}</td></tr>
    <tr><td class="k">Fecha</td><td class="v">{{ fecha }}</td></tr>
    {% if ip %}<tr><td class="k">Origen (IP)</td><td class="v">{{ ip }}</td></tr>{% endif %}
  </table>
  <p style="margin-top:16px;padding:12px;background:#fef2f2;border-left:3px solid #ef4444;
     font-size:13px;color:#7f1d1d;">
     <b>¿No realizó usted este cambio?</b> Su cuenta podría estar comprometida. Restablezca su
     contraseña de inmediato y comuníquese con el equipo de TI.</p>
  <div class="footer">Sistema Inventario Lombardi · seguridad de la cuenta</div>
</div>
""",
    "2fa_code": """
{{ style }}
<div class="card">
  <h1>Su código de verificación</h1>
  <p>Hola {{ persona_nombre }},</p>
  <p>Utilice este código para completar su inicio de sesión en <b>{{ username }}</b>
     (válido por {{ minutos }} minutos):</p>
  <p style="font-size:30px;font-weight:bold;letter-spacing:8px;text-align:center;
     margin:18px 0;color:#0f172a;">{{ code }}</p>
  <p style="font-size:13px;color:#6b7280;">Si usted no intentó iniciar sesión, puede ignorar
     este correo; le recomendamos cambiar su contraseña.</p>
  <div class="footer">Sistema Inventario Lombardi · verificación en dos pasos</div>
</div>
""",
    "password_reset": """
{{ style }}
<div class="card">
  <h1>Restablecimiento de contraseña</h1>
  <p>Hola {{ persona_nombre }},</p>
  <p>Recibimos una solicitud para restablecer la contraseña de su cuenta
     <b>{{ username }}</b>. Si fue usted, utilice el siguiente enlace (válido por
     {{ minutos }} minutos):</p>
  <p style="margin:16px 0;">
    <a href="{{ reset_url }}" style="display:inline-block;padding:10px 18px;
       background:#0ea5e9;color:#fff;border-radius:6px;text-decoration:none;font-weight:600;">
       Restablecer contraseña</a>
  </p>
  <p style="font-size:13px;color:#6b7280;">O bien, copie este código en la pantalla de
     restablecimiento:</p>
  <p style="font-family:monospace;font-size:13px;word-break:break-all;
     background:#f3f4f6;padding:10px;border-radius:6px;">{{ token }}</p>
  <p style="font-size:13px;color:#6b7280;">Si usted no lo solicitó, puede ignorar este
     correo: su contraseña no cambiará.</p>
  <div class="footer">Sistema Inventario Lombardi · seguridad de la cuenta</div>
</div>
""",
    "garantia_por_vencer": """
{{ style }}
<div class="card">
  <h1>Garantías por vencer</h1>
  <p>Hay <strong>{{ total }}</strong> activo(s) con garantía vencida o por vencer
     en los próximos {{ dias }} días:</p>
  <table>
    <tr><td class="k" style="font-weight:600;color:#374151;">Activo</td>
        <td class="k" style="font-weight:600;color:#374151;">Fin garantía</td>
        <td class="k" style="font-weight:600;color:#374151;">Estado</td></tr>
    {% for it in items %}
    <tr><td class="v">{{ it.codigo }}</td>
        <td class="v">{{ it.fin }}</td>
        <td class="v">{{ it.estado }}{% if it.dias is not none %} ({{ it.dias }}d){% endif %}</td></tr>
    {% endfor %}
  </table>
  <div class="footer">Sistema Inventario Lombardi · alerta automática de garantías</div>
</div>
""",
    "ad_sync_pendientes": """
{{ style }}
<div class="card">
  <h1>Active Directory: salidas pendientes</h1>
  <p>La sincronización con Active Directory encontró cuentas deshabilitadas o
     eliminadas cuyas personas todavía tienen activos asignados. No se
     desactivaron: procese su <strong>offboarding</strong> en el sistema.</p>
  <table>
    <tr><td class="k" style="font-weight:600;color:#374151;">Persona</td>
        <td class="k" style="font-weight:600;color:#374151;">Email</td>
        <td class="k" style="font-weight:600;color:#374151;">Activos</td></tr>
    {% for it in items %}
    <tr><td class="v">{{ it.nombre }}</td>
        <td class="v">{{ it.email }}</td>
        <td class="v">{{ it.activos }}</td></tr>
    {% endfor %}
  </table>
  <div class="footer">Sistema Inventario Lombardi · sincronización con Active Directory</div>
</div>
""",
    "nuevo_dispositivo": """
{{ style }}
<div class="card">
  <h1>Nuevo inicio de sesión en su cuenta</h1>
  <p>Hola {{ persona_nombre }},</p>
  <p>Detectamos un inicio de sesión en su cuenta <b>{{ username }}</b> desde un
     dispositivo que no habíamos visto antes.</p>
  <table>
    <tr><td class="k">Dispositivo</td><td class="v">{{ dispositivo }}</td></tr>
    <tr><td class="k">Fecha</td><td class="v">{{ fecha }}</td></tr>
    {% if ip %}<tr><td class="k">Origen (IP)</td><td class="v">{{ ip }}</td></tr>{% endif %}
  </table>
  <p style="margin-top:16px;padding:12px;background:#fef2f2;border-left:3px solid #ef4444;
     font-size:13px;color:#7f1d1d;">
     <b>¿No fue usted?</b> Cierre esa sesión desde «Seguridad de la cuenta», cambie su
     contraseña de inmediato y comuníquese con el equipo de TI.</p>
  <div class="footer">Sistema Inventario Lombardi · seguridad de la cuenta</div>
</div>
""",
    "cuenta_desactivada_inactividad": """
{{ style }}
<div class="card">
  <h1>Su cuenta fue desactivada por inactividad</h1>
  <p>Hola {{ persona_nombre }},</p>
  <p>Su cuenta <b>{{ username }}</b> no registra inicios de sesión en los últimos
     {{ dias }} días y, por la política de seguridad, fue desactivada automáticamente.</p>
  <p style="font-size:13px;color:#6b7280;">Si aún necesita acceso al sistema, solicite
     su reactivación al administrador de seguridad.</p>
  <div class="footer">Sistema Inventario Lombardi · seguridad de la cuenta</div>
</div>
""",
}

_jinja_env = Environment(loader=BaseLoader(), autoescape=True)
_SUBJECTS = {
    "asignacion": "[Inventario] Activo asignado: {codigo}",
    "devolucion": "[Inventario] Activo devuelto: {codigo}",
    "transferencia": "[Inventario] Transferencia de activo: {codigo}",
    "baja": "[Inventario] Activo dado de baja: {codigo}",
    "offboarding": "[Inventario] Salida de empleado: {persona_nombre}",
    "mantenimiento_abierto": "[Inventario] Mantenimiento abierto: {codigo}",
    "mantenimiento_cerrado": "[Inventario] Mantenimiento cerrado: {codigo}",
    "stock_bajo": "[Inventario] Stock bajo: {codigo}",
    "garantia_por_vencer": "[Inventario] Garantias por vencer: {total} activo(s)",
    "ad_sync_pendientes": "[Inventario] Active Directory: {total} salida(s) pendiente(s) con activos",
    "password_reset": "[Inventario] Restablecimiento de contrasena",
    "password_changed": "[Inventario] Su contrasena fue cambiada",
    "2fa_code": "[Inventario] Codigo de verificacion: {code}",
    "nuevo_dispositivo": "[Inventario] Nuevo inicio de sesion en su cuenta",
    "cuenta_desactivada_inactividad": "[Inventario] Su cuenta fue desactivada por inactividad",
}


class _SafeDict(dict):
    """Para str.format_map: claves ausentes -> '' en vez de KeyError."""
    def __missing__(self, key):  # noqa: D401
        return ""


def _render(template_name: str, ctx: dict[str, Any]) -> tuple[str, str]:
    """Renderiza (subject, html_body) para el template y contexto dados.

    El bloque del operador ("Ejecutado por: X") se renderiza primero como
    sub-template para evitar tener que repetirlo en cada plantilla. Pasamos
    el HTML resultante como `operator_block` al template principal.
    """
    if template_name not in _TEMPLATES:
        raise ValueError(f"Template desconocido: {template_name}")
    # `operator_block` ya fue renderizado por Jinja con autoescape (los
    # nombres del operador / reply_to están escapados internamente).
    # Lo marcamos como Markup para que el outer render NO lo re-escape
    # (perderíamos el HTML). Misma lógica para el bloque de estilos.
    operator_block = _jinja_env.from_string(_OPERATOR_BLOCK).render(**ctx)
    body = _jinja_env.from_string(_TEMPLATES[template_name]).render(
        style=Markup(_BASE_STYLE),
        operator_block=Markup(operator_block),
        **ctx,
    )
    subject = _SUBJECTS[template_name].format_map(_SafeDict(ctx))
    return subject, body


def _admin_recipients() -> list[str]:
    """Destinatarios en copia de todos los eventos (NOTIFY_ADMIN_EMAILS, CSV)."""
    raw = settings.NOTIFY_ADMIN_EMAILS or ""
    return [e.strip() for e in raw.split(",") if e.strip()]


class MailSendError(Exception):
    """Fallo de entrega. `code`: CONNECTION_FAILED | TLS_FAILED | SENDER_REJECTED | NOT_CONFIGURED | ERROR."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message


class MailAuthError(MailSendError):
    """Credenciales de la cuenta de servicio rechazadas (dispara el cortacircuitos)."""

    def __init__(self, message: str = "", code: str = "AUTH_FAILED") -> None:
        super().__init__(code, message)


def _build_message(cfg, to: list[str], subject: str, html: str, reply_to: str | None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{cfg.from_name} <{cfg.from_email}>"
    msg["To"] = ", ".join(to)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg.set_content("HTML email required.")
    msg.add_alternative(html, subtype="html")
    return msg


async def _smtp_deliver(cfg, to: list[str], subject: str, html: str, reply_to: str | None) -> None:
    import ssl
    import aiosmtplib

    try:
        await aiosmtplib.send(
            _build_message(cfg, to, subject, html, reply_to),
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.username if cfg.password else None,
            password=cfg.password or None,
            use_tls=cfg.security == "SSL",
            start_tls=cfg.security == "STARTTLS",
            timeout=cfg.timeout,
        )
    except aiosmtplib.SMTPAuthenticationError as e:
        raise MailAuthError(str(e)[:300]) from e
    except aiosmtplib.SMTPSenderRefused as e:
        raise MailSendError("SENDER_REJECTED", str(e)[:300]) from e
    except ssl.SSLError as e:
        raise MailSendError("TLS_FAILED", str(e)[:300]) from e
    except (aiosmtplib.SMTPConnectError, aiosmtplib.SMTPTimeoutError, aiosmtplib.SMTPServerDisconnected, OSError) as e:
        raise MailSendError("CONNECTION_FAILED", f"{type(e).__name__}: {str(e)[:250]}") from e
    except aiosmtplib.SMTPException as e:
        raise MailSendError("ERROR", f"{type(e).__name__}: {str(e)[:250]}") from e


_graph_token: dict[str, Any] = {}


async def _graph_access_token(cfg) -> str:
    """Token app-only (client credentials) para Microsoft Graph, cacheado hasta su expiración."""
    import time
    import httpx

    key = (cfg.graph_tenant_id, cfg.graph_client_id, cfg.graph_client_secret)
    hit = _graph_token.get("value")
    if hit and _graph_token.get("key") == key and _graph_token.get("exp", 0) > time.time() + 60:
        return hit
    async with httpx.AsyncClient(timeout=cfg.timeout) as client:
        r = await client.post(
            f"https://login.microsoftonline.com/{cfg.graph_tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": cfg.graph_client_id,
                "client_secret": cfg.graph_client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
    if r.status_code in (400, 401):
        raise MailAuthError(r.json().get("error_description", "")[:300] if r.headers.get("content-type", "").startswith("application/json") else r.text[:300])
    if r.status_code >= 300:
        raise MailSendError("CONNECTION_FAILED", f"token HTTP {r.status_code}")
    data = r.json()
    _graph_token.update(key=key, value=data["access_token"], exp=time.time() + int(data.get("expires_in", 3600)))
    return data["access_token"]


async def _graph_deliver(cfg, to: list[str], subject: str, html: str, reply_to: str | None) -> None:
    """Envío con Microsoft Graph /users/{buzón}/sendMail (permiso de aplicación Mail.Send)."""
    import httpx

    try:
        token = await _graph_access_token(cfg)
        message: dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to],
        }
        if reply_to:
            message["replyTo"] = [{"emailAddress": {"address": reply_to}}]
        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            r = await client.post(
                f"https://graph.microsoft.com/v1.0/users/{cfg.from_email}/sendMail",
                headers={"Authorization": f"Bearer {token}"},
                json={"message": message, "saveToSentItems": False},
            )
    except httpx.HTTPError as e:
        raise MailSendError("CONNECTION_FAILED", f"{type(e).__name__}: {str(e)[:250]}") from e
    if r.status_code == 202:
        return
    if r.status_code in (401, 403):
        _graph_token.clear()
        raise MailAuthError(f"Graph HTTP {r.status_code}: {r.text[:250]}")
    if r.status_code == 404:
        raise MailSendError("SENDER_REJECTED", f"Buzón no encontrado: {cfg.from_email}")
    raise MailSendError("ERROR", f"Graph HTTP {r.status_code}: {r.text[:250]}")


async def deliver_with_config(
    cfg, to: list[str], subject: str, html: str, reply_to: str | None = None,
    *, use_breaker: bool = True,
) -> None:
    """
    Entrega un correo con una MailConfig concreta (SMTP o Graph). Si
    `use_breaker`, respeta el cortacircuitos y lo dispara ante un fallo de
    autenticación. Las pruebas desde la UI usan use_breaker=False.
    """
    from app.services.integration_config import breaker_until, trip_breaker

    if not cfg.ready:
        raise MailSendError("NOT_CONFIGURED")
    if use_breaker and await breaker_until("smtp"):
        raise MailAuthError("", code="AUTH_PAUSED")
    try:
        if cfg.provider == "GRAPH":
            await _graph_deliver(cfg, to, subject, html, reply_to)
        else:
            await _smtp_deliver(cfg, to, subject, html, reply_to)
    except MailSendError as e:
        _delivery_metrics["failed_total"] += 1
        _delivery_metrics["last_delivery_ok"] = False
        _delivery_metrics["last_error_type"] = e.code
        if isinstance(e, MailAuthError) and use_breaker:
            await trip_breaker("smtp", str(e))
        raise
    _delivery_metrics["sent_total"] += 1
    _delivery_metrics["last_delivery_ok"] = True
    log.info("email.sent", to=to, subject=subject, provider=cfg.provider)


async def _smtp_send_once(
    to: list[str], subject: str, html: str, reply_to: str | None = None,
) -> None:
    """Un intento de entrega con la config efectiva. Lanza MailSendError si falla."""
    from app.services.integration_config import get_config
    await deliver_with_config((await get_config()).mail, to, subject, html, reply_to)


async def _send_via_smtp_with_retry(
    to: list[str],
    subject: str,
    html: str,
    reply_to: str | None = None,
    max_retries: int = 3,
    initial_delay: float = 1.0,
) -> None:
    """
    Envío directo en memoria con reintentos cortos. Solo para correos
    efímeros con secretos (reset de contraseña, códigos 2FA): no deben
    persistirse en la cola y pierden valor en minutos.
    """
    if not await _delivery_configured():
        log.info("email.silenced", to=to, subject=subject)
        return
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            await _smtp_send_once(to, subject, html, reply_to)
            return
        except MailAuthError as e:
            log.error("email.auth_failed", to=to, subject=subject, error=str(e)[:100])
            return  # reintentar con la misma clave solo acercaría un bloqueo de cuenta
        except Exception as e:  # noqa: BLE001
            log.warning("email.send_attempt_failed", attempt=attempt, error=str(e)[:100])
            if attempt == max_retries:
                log.error("email.max_retries_reached", to=to, subject=subject)
            else:
                await asyncio.sleep(delay)
                delay *= 2


_background_tasks: set[asyncio.Task] = set()

# Plantillas con secretos de un solo uso: nunca se guardan en la cola.
_EPHEMERAL_TEMPLATES = frozenset({"password_reset", "2fa_code"})


async def _as_system(coro) -> None:
    from app.core.data_scope import system_scope
    with system_scope():
        await coro


def _spawn(coro) -> None:
    """create_task conservando referencia (evita que el GC cancele el envío).
    La tarea corre en modo sistema: no hereda el alcance por sede del usuario."""
    task = asyncio.create_task(_as_system(coro))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _delivery_configured() -> bool:
    from app.services.integration_config import get_config
    return (await get_config()).mail.ready


async def send_notification(
    template_name: str,
    ctx: dict[str, Any],
    to: Iterable[str] = (),
    cc_admins: bool = True,
    reply_to: str | None = None,
    operator_name: str | None = None,
    operator_role: str | None = None,
    affected: Iterable[str] | None = None,
) -> None:
    """
    API pública. Encola el correo en la cola persistente (SYS_EMAIL_OUTBOX);
    el worker lo entrega con reintentos (app/services/email_outbox.py).

    `to` son los destinatarios directos que propone la gestión; `affected` las
    personas involucradas (por defecto = `to`), usadas para resolver jefes y
    la opción "notificar afectado" de las reglas por evento. Los eventos no
    configurables se envían solo a `to` (+ admins si cc_admins).

    Nunca lanza por fallos de entrega: si la cola no está disponible, se
    intenta un envío directo en memoria.
    """
    from app.services.notification_rules import CONFIGURABLE_EVENTS

    to_list = [e for e in to if e]
    affected_list = [e for e in affected if e] if affected is not None else None

    enriched_ctx = {
        **ctx,
        "operator_name": operator_name or "Sistema",
        "operator_role": operator_role or "",
        "reply_to": reply_to or "",
    }
    subject, html = _render(template_name, enriched_ctx)

    if not await _delivery_configured():
        log.info("email.silenced", template=template_name, subject=subject)
        return

    legacy = list({e for e in [*to_list, *(_admin_recipients() if cc_admins else [])] if e})
    if template_name in _EPHEMERAL_TEMPLATES:
        if legacy:
            _spawn(_send_via_smtp_with_retry(legacy, subject, html, reply_to=reply_to))
        return

    configurable = template_name in CONFIGURABLE_EVENTS
    if not configurable and not legacy:
        return
    try:
        from app.services import email_outbox
        await email_outbox.enqueue(
            template=template_name, subject=subject, html=html,
            to=to_list if configurable else legacy,
            affected=affected_list, cc_admins=cc_admins,
            resolve=configurable, reply_to=reply_to,
        )
    except Exception as e:  # noqa: BLE001
        log.error("email.enqueue_failed", template=template_name, error=str(e)[:200])
        if legacy:
            _spawn(_send_via_smtp_with_retry(legacy, subject, html, reply_to=reply_to))


async def notify_password_changed(
    *, persona_nombre: str, username: str, to_email: str | None,
    metodo: str, ip: str | None = None,
) -> None:
    """
    Aviso de seguridad al DUEÑO de la cuenta de que su contraseña cambió.
    Solo al usuario (cc_admins=False); fire-and-forget. No-op si no hay correo.
    """
    if not to_email:
        return
    from datetime import datetime, timezone
    await send_notification(
        "password_changed",
        {
            "persona_nombre": persona_nombre,
            "username": username,
            "metodo": metodo,
            "fecha": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
            "ip": ip or "",
        },
        to=[to_email],
        cc_admins=False,
    )


async def notify_security_event(
    template_name: str, *, persona_nombre: str, username: str, to_email: str | None, **ctx: Any,
) -> None:
    """Aviso de seguridad solo al titular de la cuenta (sin copia a administradores)."""
    if not to_email:
        return
    from datetime import datetime, timezone
    await send_notification(
        template_name,
        {
            "persona_nombre": persona_nombre,
            "username": username,
            "fecha": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
            **ctx,
        },
        to=[to_email],
        cc_admins=False,
    )


def send_notification_sync_for_tests(
    template_name: str, ctx: dict[str, Any], to: Iterable[str] = (),
) -> tuple[str, str, list[str]]:
    """
    Variante sincrónica para tests: NO envía, sólo retorna lo que enviaría.
    Útil para verificar templates y destinatarios sin un MailHog corriendo.
    """
    recipients = list({e for e in [*to, *_admin_recipients()] if e})
    subject, html = _render(template_name, ctx)
    return subject, html, recipients
