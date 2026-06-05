import uuid
from sqlalchemy import (
    Column, Integer, String, ForeignKey, DateTime, func, JSON, Uuid, Index, Boolean,
)
from sqlalchemy.orm import relationship
from app.db.base import Base


# ==========================================
# 1. AUDITORÍA FORENSE
# ==========================================
class AuditoriaSistema(Base):
    __tablename__ = "INV_AUDITORIA_SISTEMA"

    AUD_Auditoria = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)

    AUD_Fecha_Hora = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    AUD_Accion = Column(String(50), nullable=False)
    AUD_Entidad_Afectada = Column(String(50), nullable=False, index=True)
    AUD_Snapshot_JSON = Column(JSON, nullable=True)
    AUD_IP_Origen = Column(String(45), nullable=True)
    AUD_User_Agent = Column(String(255), nullable=True)

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
    SYS_Color_Primario = Column(String(10), default="#1e293b")
    SYS_Color_Secundario = Column(String(10), default="#3b82f6")
    # Color del fondo de la app (independiente del primario, que solo tiñe el
    # brillo del gradiente). Default: slate oscuro, no negro puro.
    SYS_Color_Fondo = Column(String(10), default="#0f172a")
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
    IDK_Response_Status = Column(Integer, nullable=False)
    IDK_Response_Body = Column(JSON, nullable=True)
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
