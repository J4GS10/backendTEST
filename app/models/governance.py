import uuid
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.base import Base

# ==========================================
# 1. AUDITORÍA FORENSE (Caja Negra)
# ==========================================
class AuditoriaSistema(Base):
    __tablename__ = "INV_AUDITORIA_SISTEMA"

    AUD_Auditoria = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    AUD_Fecha_Hora = Column(DateTime, server_default=func.now())
    AUD_Accion = Column(String(50), nullable=False) # CREATE, UPDATE, DELETE_LOGIC
    AUD_Entidad_Afectada = Column(String(50), nullable=False) # INV_ACTIVO
    AUD_Snapshot_JSON = Column(JSONB, nullable=True) # El "antes" y "después"
    AUD_IP_Origen = Column(String(45), nullable=True)

    # FK al Actor (Usuario)
    USU_Usuario = Column(UUID(as_uuid=True), ForeignKey("INV_USUARIO.USU_Usuario"), nullable=True) 


# ==========================================
# 2. CONFIGURACIÓN (Singleton)
# ==========================================
class ConfiguracionSistema(Base):
    __tablename__ = "SYS_CONFIGURACION"

    SYS_Configuracion = Column(Integer, primary_key=True, default=1) # Siempre será 1
    
    SYS_Nombre_Empresa = Column(String(100), default="Mi Empresa")
    SYS_Logo_URL = Column(String(255), nullable=True)
    SYS_Color_Primario = Column(String(10), default="#1e293b") # Hex
    SYS_Color_Secundario = Column(String(10), default="#3b82f6")
    SYS_Idioma_Defecto = Column(String(2), default="es")

# ==========================================
# 3. MOTOR DE SECUENCIAS (Generador de Códigos)
# ==========================================
class Secuencia(Base):
    __tablename__ = "SYS_SECUENCIA"

    SEC_Secuencia = Column(Integer, primary_key=True, index=True, autoincrement=True)
    
    # Identificador del contexto (Ej: "ASSET_LPT", "DOC_ACTA")
    SEC_Contexto = Column(String(50), unique=True, nullable=False)
    
    SEC_Ultimo_Numero = Column(Integer, default=0, nullable=False)
    SEC_Relleno = Column(Integer, default=5, nullable=False) # Por defecto 5 ceros (00001)