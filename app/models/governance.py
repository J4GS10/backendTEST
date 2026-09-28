import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, ForeignKey, DateTime, func, Uuid, Index, Boolean, Text, CheckConstraint,
)
from sqlalchemy.orm import relationship
from app.db.base import Base
from app.db.types import PortableJSON


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ==========================================
# 1. AUDITORÍA FORENSE
# ==========================================
class AuditoriaSistema(Base):
    __tablename__ = "INV_AUDITORIA_SISTEMA"

    AUD_Auditoria = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)

    # Valor generado en Python (además del server_default): así el INSERT no
    # necesita RETURNING, que la política RLS de lectura podría rechazar para
    # un evento que el usuario registra pero no puede leer.
    AUD_Fecha_Hora = Column(
        DateTime, default=_utcnow_naive, server_default=func.now(), nullable=False, index=True,
    )
    AUD_Accion = Column(String(50), nullable=False)
    AUD_Entidad_Afectada = Column(String(50), nullable=False, index=True)
    AUD_Snapshot_JSON = Column(PortableJSON(), nullable=True)
    AUD_IP_Origen = Column(String(45), nullable=True)
    AUD_User_Agent = Column(String(255), nullable=True)
    # Sede del registro afectado (eventos de inventario). Permite que un auditor
    # con alcance por sede vea solo la bitácora de sus sedes. Sin FK: la
    # bitácora no debe cambiar si una sede se elimina.
    AUD_Sede = Column(Integer, nullable=True, index=True)

    # SET NULL: preservamos la bitácora aunque el usuario se elimine.
    USU_Usuario = Column(
        Uuid,
        ForeignKey("INV_USUARIO.USU_Usuario", ondelete="SET NULL"),
        nullable=True,
    )

    usuario = relationship("app.models.organization.Usuario")

    __table_args__ = (
        Index("ix_auditoria_usuario_fecha", "USU_Usuario", "AUD_Fecha_Hora"),
    )


# ==========================================
# 2. CONFIGURACIÓN (Singleton)
# ==========================================
class ConfiguracionSistema(Base):
    __tablename__ = "SYS_CONFIGURACION"

    SYS_Configuracion = Column(Integer, primary_key=True, default=1)
    SYS_Nombre_Empresa = Column(String(100), default="Mi Empresa")
    SYS_Logo_URL = Column(String(500), nullable=True)
    SYS_Color_Primario = Column(String(10), default="#4a7c9e")
    SYS_Color_Secundario = Column(String(10), default="#5a8e7a")
    # Color del fondo de la app (independiente del primario, que solo tiñe el
    # brillo del gradiente). Default: slate oscuro, no negro puro.
    SYS_Color_Fondo = Column(String(10), default="#f5f3ef")
    SYS_Idioma_Defecto = Column(String(2), default="es")
    # Datos del encabezado de las actas (Word/PDF).
    SYS_Codigo_Formulario = Column(String(50), nullable=True)
    SYS_Ciudad = Column(String(60), nullable=True)


# ==========================================
# 3. SECUENCIAS
# ==========================================
class Secuencia(Base):
    __tablename__ = "SYS_SECUENCIA"

    SEC_Secuencia = Column(Integer, primary_key=True, index=True, autoincrement=True)
    SEC_Contexto = Column(String(50), unique=True, nullable=False)
    SEC_Ultimo_Numero = Column(Integer, default=0, nullable=False)
    SEC_Relleno = Column(Integer, default=5, nullable=False)


# ==========================================
# 4. TOKENS REVOCADOS (blacklist por jti)
# ==========================================
class IdempotencyKey(Base):
    """
    Cache de respuestas para POSTs marcados con cabecera 'Idempotency-Key'.
    Si el cliente re-envía la misma key dentro de la ventana de retención
    (24h), devolvemos la respuesta original sin re-ejecutar la lógica.
    """
    __tablename__ = "SYS_IDEMPOTENCY_KEY"

    IDK_Key = Column(String(128), primary_key=True)
    IDK_Endpoint = Column(String(200), nullable=False)
    IDK_Usuario = Column(
        Uuid,
        ForeignKey("INV_USUARIO.USU_Usuario", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    IDK_Request_Hash = Column(String(64), nullable=False)
    IDK_Estado = Column(String(16), nullable=False, default="PENDING")
    IDK_Response_Status = Column(Integer, nullable=False)
    IDK_Response_Body = Column(PortableJSON(), nullable=True)
    IDK_Creada_En = Column(DateTime, server_default=func.now(), nullable=False, index=True)


class PasswordResetToken(Base):
    """
    Token de restablecimiento de contraseña (flujo "olvidé mi contraseña").
    Se guarda SOLO el hash SHA-256 del token; el token plano se envía por email
    al correo corporativo del usuario. De un solo uso (PRT_Usado) y con expiración.
    """
    __tablename__ = "SYS_PASSWORD_RESET"

    PRT_Id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    PRT_Token_Hash = Column(String(64), unique=True, nullable=False, index=True)
    PRT_Expira = Column(DateTime, nullable=False, index=True)
    PRT_Usado = Column(Boolean, default=False, nullable=False)
    PRT_Creado_En = Column(DateTime, server_default=func.now(), nullable=False)

    USU_Usuario = Column(
        Uuid,
        ForeignKey("INV_USUARIO.USU_Usuario", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class TwoFactorCode(Base):
    """
    Código OTP de un solo uso para 2FA por EMAIL (se envía en cada login).
    Se guarda solo el hash; expira y tiene tope de intentos.
    """
    __tablename__ = "SYS_2FA_CODE"

    TFC_Id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    TFC_Code_Hash = Column(String(64), nullable=False, index=True)
    TFC_Expira = Column(DateTime, nullable=False, index=True)
    TFC_Usado = Column(Boolean, default=False, nullable=False)
    TFC_Intentos = Column(Integer, default=0, nullable=False)
    TFC_Creado_En = Column(DateTime, server_default=func.now(), nullable=False)

    USU_Usuario = Column(
        Uuid, ForeignKey("INV_USUARIO.USU_Usuario", ondelete="CASCADE"),
        nullable=False, index=True,
    )


class RecoveryCode(Base):
    """Código de recuperación 2FA (un solo uso, hash). Para cuando se pierde el 2º factor."""
    __tablename__ = "SYS_2FA_RECOVERY"

    TRC_Id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    TRC_Code_Hash = Column(String(64), nullable=False, index=True)
    TRC_Usado = Column(Boolean, default=False, nullable=False)
    TRC_Creado_En = Column(DateTime, server_default=func.now(), nullable=False)

    USU_Usuario = Column(
        Uuid, ForeignKey("INV_USUARIO.USU_Usuario", ondelete="CASCADE"),
        nullable=False, index=True,
    )


class TokenRevocado(Base):
    """
    Blacklist de jti revocados (logout, cambio de contraseña, etc.).
    Limpieza periódica: WHERE TRV_Expira < now().
    """
    __tablename__ = "SYS_TOKEN_REVOCADO"

    TRV_Jti = Column(String(64), primary_key=True)
    TRV_Tipo = Column(String(10), nullable=False)  # 'access' | 'refresh'
    TRV_Fecha_Revocacion = Column(DateTime, server_default=func.now(), nullable=False)
    TRV_Expira = Column(DateTime, nullable=False, index=True)
    USU_Usuario = Column(
        Uuid,
        ForeignKey("INV_USUARIO.USU_Usuario", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )


class ReglaNotificacion(Base):
    """
    Regla de destinatarios por tipo de gestión (evento de email). Si no existe
    fila para un evento se aplican los valores por defecto del código
    (app/services/notification_rules.py).
    """
    __tablename__ = "INV_REGLA_NOTIFICACION"

    RNO_Evento = Column(String(50), primary_key=True)
    RNO_Activa = Column(Boolean, default=True, nullable=False)
    RNO_Notificar_Afectado = Column(Boolean, default=True, nullable=False)
    RNO_Notificar_Jefe = Column(Boolean, default=False, nullable=False)
    RNO_Copiar_Admins = Column(Boolean, default=True, nullable=False)
    RNO_Grupos_AD = Column(String(1000), nullable=True)  # CSV de nombres de grupo
    RNO_Correos_Extra = Column(String(1000), nullable=True)  # CSV de emails
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class EmailOutbox(Base):
    """
    Cola persistente de correos (patrón outbox). Sobrevive a reinicios y a
    caídas del SMTP: un worker en cada proceso la drena con
    SELECT ... FOR UPDATE SKIP LOCKED y reintentos con backoff.
    Los correos con secretos (reset de contraseña, códigos 2FA) NO pasan por
    aquí: se envían directo para no persistir tokens en la BD.
    """
    __tablename__ = "SYS_EMAIL_OUTBOX"

    EOB_Id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    EOB_Plantilla = Column(String(50), nullable=False)
    EOB_Asunto = Column(String(255), nullable=False)
    EOB_Html = Column(Text, nullable=False)
    # Destinatarios directos; si EOB_Resolver=True el worker aplica las reglas
    # de notificación (jefe, grupos AD...) en el primer intento y los fija aquí.
    EOB_Para = Column(PortableJSON(), nullable=False)
    EOB_Afectados = Column(PortableJSON(), nullable=True)
    EOB_Cc_Admins = Column(Boolean, default=True, nullable=False)
    EOB_Resolver = Column(Boolean, default=False, nullable=False)
    EOB_Reply_To = Column(String(150), nullable=True)
    EOB_Estado = Column(String(10), default="PENDIENTE", nullable=False)  # PENDIENTE | ENVIADO | FALLIDO
    EOB_Intentos = Column(Integer, default=0, nullable=False)
    EOB_Proximo_Intento = Column(DateTime, nullable=False)
    EOB_Ultimo_Error = Column(String(500), nullable=True)
    EOB_Creado_En = Column(DateTime, server_default=func.now(), nullable=False)
    EOB_Enviado_En = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_email_outbox_pendientes", "EOB_Estado", "EOB_Proximo_Intento"),
    )


class IntegracionCorreo(Base):
    """
    Configuración (fila única, id=1) de la cuenta de servicio genérica usada
    para ENVIAR correos y, opcionalmente, para vincularse al Active Directory.
    Cuando existe, prevalece sobre las variables de entorno SMTP_*/AD_*.
    Los secretos se guardan cifrados con FIELD_ENCRYPTION_KEY (Fernet).
    """
    __tablename__ = "SYS_INTEGRACION_CORREO"

    INT_Id = Column(Integer, primary_key=True, default=1)
    INT_Modo = Column(String(12), nullable=False, default="DESACTIVADO")  # DESACTIVADO | CORREO | CORREO_AD
    INT_Proveedor = Column(String(10), nullable=False, default="SMTP")  # SMTP | GRAPH

    INT_Cuenta_Email = Column(String(150), nullable=True)
    INT_Cuenta_Usuario = Column(String(150), nullable=True)
    INT_Cuenta_Password_Enc = Column(String(1000), nullable=True)
    INT_Nombre_Remitente = Column(String(100), nullable=True)

    INT_SMTP_Host = Column(String(150), nullable=True)
    INT_SMTP_Puerto = Column(Integer, nullable=False, default=587)
    INT_SMTP_Seguridad = Column(String(10), nullable=False, default="STARTTLS")  # STARTTLS | SSL | NINGUNA

    INT_Graph_Tenant_Id = Column(String(100), nullable=True)
    INT_Graph_Client_Id = Column(String(100), nullable=True)
    INT_Graph_Secret_Enc = Column(String(1000), nullable=True)

    INT_AD_Servidor = Column(String(300), nullable=True)
    INT_AD_Base_DN = Column(String(300), nullable=True)
    INT_AD_Grupo_Base_DN = Column(String(300), nullable=True)
    INT_AD_Grupo_Admin = Column(String(150), nullable=True)
    INT_AD_Start_TLS = Column(Boolean, nullable=False, default=False)
    INT_AD_Verificar_Cert = Column(Boolean, nullable=False, default=True)
    INT_AD_Intervalo_Min = Column(Integer, nullable=False, default=0)
    INT_AD_Desactivar = Column(Boolean, nullable=False, default=True)
    INT_AD_Usar_Cuenta_Servicio = Column(Boolean, nullable=False, default=True)
    INT_AD_Bind_Usuario = Column(String(150), nullable=True)
    INT_AD_Bind_Password_Enc = Column(String(1000), nullable=True)

    INT_Actualizado_En = Column(DateTime, server_default=func.now(), onupdate=func.now())
    USU_Actualizado_Por = Column(Uuid, nullable=True)

    __table_args__ = (
        CheckConstraint('"INT_Id" = 1', name="ck_integracion_fila_unica"),
        CheckConstraint("\"INT_Modo\" IN ('DESACTIVADO','CORREO','CORREO_AD')", name="ck_integracion_modo"),
        CheckConstraint("\"INT_Proveedor\" IN ('SMTP','GRAPH')", name="ck_integracion_proveedor"),
        CheckConstraint("\"INT_SMTP_Seguridad\" IN ('STARTTLS','SSL','NINGUNA')", name="ck_integracion_smtp_seguridad"),
    )



# ==========================================
# SESIONES Y CONTRASEÑAS
# ==========================================
class Sesion(Base):
    """
    Sesión de inicio (una por login). Los tokens llevan su id en el claim
    `sid`: cerrar una sesión invalida sus tokens sin afectar a las demás.
    """
    __tablename__ = "SYS_SESION"

    SES_Sesion = Column(Uuid, primary_key=True, default=uuid.uuid4)
    USU_Usuario = Column(
        Uuid, ForeignKey("INV_USUARIO.USU_Usuario", ondelete="CASCADE"), nullable=False, index=True,
    )
    SES_Creada_En = Column(DateTime, server_default=func.now(), nullable=False)
    SES_Ultima_Actividad = Column(DateTime, server_default=func.now(), nullable=False)
    SES_Expira = Column(DateTime, nullable=False)
    SES_IP = Column(String(45), nullable=True)
    SES_User_Agent = Column(String(255), nullable=True)
    # Huella corta del dispositivo ("Chrome · Windows") para detectar equipos nuevos.
    SES_Dispositivo = Column(String(60), nullable=True)
    SES_Metodo = Column(String(10), nullable=False, default="password")  # password | 2fa | sso
    SES_Refresh_Jti = Column(String(64), nullable=True)
    SES_Cerrada_En = Column(DateTime, nullable=True)
    SES_Motivo_Cierre = Column(String(30), nullable=True)

    __table_args__ = (
        Index("ix_sesion_usuario_activa", "USU_Usuario", "SES_Cerrada_En"),
    )


class PasswordHistorial(Base):
    """Hashes de contraseñas anteriores: impide reutilizar las últimas N."""
    __tablename__ = "SYS_PASSWORD_HISTORIAL"

    PWH_Id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    USU_Usuario = Column(
        Uuid, ForeignKey("INV_USUARIO.USU_Usuario", ondelete="CASCADE"), nullable=False, index=True,
    )
    PWH_Hash = Column(String(255), nullable=False)
    PWH_Creado_En = Column(
        DateTime, default=_utcnow_naive, server_default=func.now(), nullable=False, index=True,
    )
