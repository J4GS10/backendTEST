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
  <p>Se ha registrado la asignación de un activo bajo tu custodia.</p>
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
    Si recibes este activo en mano, conserva esta notificación como respaldo.
    Para devolverlo, contacta al equipo de TI.
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
  <h1>Tu contraseña fue cambiada</h1>
  <p>Hola {{ persona_nombre }},</p>
  <p>Te confirmamos que la contraseña de tu cuenta <b>{{ username }}</b> se cambió
     correctamente.</p>
  <table>
    <tr><td class="k">Cuenta</td><td class="v">{{ username }}</td></tr>
    <tr><td class="k">Método</td><td class="v">{{ metodo }}</td></tr>
    <tr><td class="k">Fecha</td><td class="v">{{ fecha }}</td></tr>
    {% if ip %}<tr><td class="k">Origen (IP)</td><td class="v">{{ ip }}</td></tr>{% endif %}
  </table>
  <p style="margin-top:16px;padding:12px;background:#fef2f2;border-left:3px solid #ef4444;
     font-size:13px;color:#7f1d1d;">
     <b>¿No fuiste tú?</b> Tu cuenta podría estar comprometida. Restablece tu
     contraseña de inmediato y contacta al equipo de TI.</p>
  <div class="footer">Sistema Inventario Lombardi · seguridad de la cuenta</div>
</div>
""",
    "2fa_code": """
{{ style }}
<div class="card">
  <h1>Tu código de verificación</h1>
  <p>Hola {{ persona_nombre }},</p>
  <p>Usa este código para completar tu inicio de sesión en <b>{{ username }}</b>
     (válido por {{ minutos }} minutos):</p>
  <p style="font-size:30px;font-weight:bold;letter-spacing:8px;text-align:center;
     margin:18px 0;color:#0f172a;">{{ code }}</p>
  <p style="font-size:13px;color:#6b7280;">Si no intentaste iniciar sesión, ignora
     este correo y considera cambiar tu contraseña.</p>
  <div class="footer">Sistema Inventario Lombardi · verificación en dos pasos</div>
</div>
""",
    "password_reset": """
{{ style }}
<div class="card">
  <h1>Restablecimiento de contraseña</h1>
  <p>Hola {{ persona_nombre }},</p>
  <p>Recibimos una solicitud para restablecer la contraseña de tu cuenta
     <b>{{ username }}</b>. Si fuiste tú, usa el siguiente enlace (válido por
     {{ minutos }} minutos):</p>
  <p style="margin:16px 0;">
    <a href="{{ reset_url }}" style="display:inline-block;padding:10px 18px;
       background:#0ea5e9;color:#fff;border-radius:6px;text-decoration:none;font-weight:600;">
       Restablecer contraseña</a>
  </p>
  <p style="font-size:13px;color:#6b7280;">O copia este código en la pantalla de
     restablecimiento:</p>
  <p style="font-family:monospace;font-size:13px;word-break:break-all;
     background:#f3f4f6;padding:10px;border-radius:6px;">{{ token }}</p>
  <p style="font-size:13px;color:#6b7280;">Si no solicitaste esto, ignora este
     correo: tu contraseña no cambiará.</p>
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
    "password_reset": "[Inventario] Restablecimiento de contrasena",
    "password_changed": "[Inventario] Tu contrasena fue cambiada",
    "2fa_code": "[Inventario] Codigo de verificacion: {code}",
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


async def _send_via_smtp(
    to: list[str],
    subject: str,
    html: str,
    reply_to: str | None = None,
) -> None:
    """Envía vía SMTP usando aiosmtplib. Maneja errores sin propagar.

    `reply_to`: email del usuario que ejecutó la acción de negocio
    (técnico, admin, etc.). Cuando un destinatario responde, el correo va
    a esta dirección — NO al sender corporativo (noreply).
    """
    if not settings.EMAIL_ENABLED or not settings.SMTP_HOST:
        log.info("email.silenced",
                 reason="EMAIL_ENABLED=False or SMTP_HOST empty",
                 to=to, subject=subject)
        return

    try:
        import aiosmtplib  # type: ignore
    except ImportError:
        log.warning("email.aiosmtplib_not_installed")
        return

    msg = EmailMessage()
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = ", ".join(to)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg.set_content("Tu cliente no soporta HTML. Abre este correo en una vista compatible.")
    msg.add_alternative(html, subtype="html")

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            use_tls=settings.SMTP_TLS and settings.SMTP_PORT == 465,
            start_tls=settings.SMTP_STARTTLS and settings.SMTP_PORT != 465,
            timeout=10,
        )
        log.info("email.sent", to=to, subject=subject, reply_to=reply_to)
    except Exception as e:  # noqa: BLE001
        # Best-effort: NO propagamos para que el fallo SMTP no aborte
        # la transacción de negocio que ya se commiteó.
        log.warning("email.send_failed",
                    to=to, subject=subject,
                    error_type=type(e).__name__, error=str(e)[:200])


def _admin_recipients() -> list[str]:
    raw = settings.NOTIFY_ADMIN_EMAILS or ""
    return [e.strip() for e in raw.split(",") if e.strip()]


async def send_notification(
    template_name: str,
    ctx: dict[str, Any],
    to: Iterable[str] = (),
    cc_admins: bool = True,
    reply_to: str | None = None,
    operator_name: str | None = None,
    operator_role: str | None = None,
) -> None:
    """
    API pública del servicio. Renderiza la plantilla, junta destinatarios
    (persona involucrada + admins según config) y dispara el SMTP en background.

    Args:
      template_name: clave en _TEMPLATES.
      ctx: contexto Jinja2 para el template.
      to: destinatarios explícitos (típicamente persona involucrada).
      cc_admins: si True, añade NOTIFY_ADMIN_EMAILS.
      reply_to: email del usuario que ejecutó la acción. El "responder" del
                destinatario llega aquí, no al noreply corporativo.
      operator_name: nombre del operador (técnico/admin) que ejecutó. Se
                     inyecta en el contexto del template para mostrar la
                     firma "Ejecutado por: ...".
      operator_role: rol del operador (SUPER_ADMIN, ADMIN_TI, TECNICO).

    NO bloquea la transacción del caller: si falla el SMTP solo se loguea.
    """
    recipients = list({e for e in [*to, *(_admin_recipients() if cc_admins else [])] if e})
    if not recipients:
        log.debug("email.no_recipients", template=template_name)
        return
    # Inyectar info del operador en el contexto del template
    enriched_ctx = {
        **ctx,
        "operator_name": operator_name or "Sistema",
        "operator_role": operator_role or "",
        "reply_to": reply_to or "",
    }
    subject, html = _render(template_name, enriched_ctx)
    # Fire-and-forget: el caller no espera el envío SMTP.
    asyncio.create_task(_send_via_smtp(recipients, subject, html, reply_to=reply_to))


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
