"""
NotificationService — Encapsula el envío de notificaciones post-commit.

Principio de diseño:
  - Nunca escribe en base de datos.
  - Solo agenda callbacks con schedule_post_commit (ContextVar).
  - Recibe todos los datos ya resueltos: el llamador es responsable de
    resolver info del operador/activo ANTES de invocar este servicio,
    dentro de la transacción activa.
  - Los errores de envío de email se absorben silenciosamente: nunca
    deben revertir la transacción principal.
"""
from __future__ import annotations

from app.core.transactional import schedule_post_commit


class NotificationService:
    """Métodos estáticos para agendar notificaciones post-commit."""

    @staticmethod
    def schedule_baja(
        *,
        activo_codigo: str,
        activo_serie: str,
        fecha_iso: str,
        operador_nombre: str = "Sistema",
        operador_email: str | None = None,
        operador_rol: str = "",
    ) -> None:
        """Agenda el envío del email de baja lógica tras el commit exitoso."""

        async def _send() -> None:
            try:
                from app.core.email import send_notification
                await send_notification(
                    "baja",
                    {
                        "codigo": activo_codigo,
                        "serie": activo_serie,
                        "fecha": fecha_iso,
                        "motivo": "Baja lógica solicitada por administrador",
                    },
                    to=(),
                    reply_to=operador_email,
                    operator_name=operador_nombre,
                    operator_role=operador_rol,
                )
            except Exception:  # noqa: BLE001
                pass

        schedule_post_commit(None, _send)
