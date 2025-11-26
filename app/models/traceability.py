import uuid
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Numeric, func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base

# ==========================================
# 1. CATÁLOGOS DE OPERACIÓN
# ==========================================
class TipoMovimiento(Base):
    __tablename__ = "INV_TIPO_MOVIMIENTO"
    TMO_Tipo_Movimiento = Column(Integer, primary_key=True, index=True, autoincrement=True)
    TMO_Nombre = Column(String(50), unique=True, nullable=False) 

class TipoMantenimiento(Base):
    __tablename__ = "INV_TIPO_MANTENIMIENTO"
    TMA_Tipo_Mantenimiento = Column(Integer, primary_key=True, index=True, autoincrement=True)
    TMA_Nombre = Column(String(50), unique=True, nullable=False)

class TipoEvidencia(Base):
    __tablename__ = "INV_TIPO_EVIDENCIA"
    TEV_Tipo_Evidencia = Column(Integer, primary_key=True, index=True, autoincrement=True)
    TEV_Nombre = Column(String(50), unique=True, nullable=False) 


# ==========================================
# 2. MOVIMIENTO (Asignaciones)
# ==========================================
class Movimiento(Base):
    __tablename__ = "INV_MOVIMIENTO"

    MOV_Movimiento = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    MOV_Fecha_Asignacion = Column(DateTime, server_default=func.now())
    MOV_Fecha_Devolucion = Column(DateTime, nullable=True) 
    MOV_Observacion = Column(Text, nullable=True)

    # FKs
    ACT_Activo = Column(UUID(as_uuid=True), ForeignKey("INV_ACTIVO.ACT_Activo"), nullable=False)
    PER_Persona = Column(UUID(as_uuid=True), ForeignKey("INV_PERSONA.PER_Persona"), nullable=False)
    ARE_Area = Column(Integer, ForeignKey("INV_AREA.ARE_Area"), nullable=False)
    TMO_Tipo_Movimiento = Column(Integer, ForeignKey("INV_TIPO_MOVIMIENTO.TMO_Tipo_Movimiento"), nullable=False)
    
    # Relaciones
    activo = relationship("app.models.core.Activo", backref="movimientos")
    persona = relationship("app.models.organization.Persona", backref="movimientos")
    
    evidencias = relationship("Evidencia", back_populates="movimiento")


# ==========================================
# 3. MANTENIMIENTO (Tickets)
# ==========================================
class Mantenimiento(Base):
    __tablename__ = "INV_MANTENIMIENTO"

    # CORRECCIÓN: Nombre Completo
    MAN_Mantenimiento = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    MAN_Fecha_Ingreso = Column(DateTime, server_default=func.now())
    MAN_Fecha_Cierre = Column(DateTime, nullable=True)
    MAN_Descripcion_Falla = Column(Text, nullable=False)
    MAN_Costo_Total = Column(Numeric(10, 2), default=0)

    # FKs
    ACT_Activo = Column(UUID(as_uuid=True), ForeignKey("INV_ACTIVO.ACT_Activo"), nullable=False)
    PER_Persona_Solicita = Column(UUID(as_uuid=True), ForeignKey("INV_PERSONA.PER_Persona"), nullable=False)
    TMA_Tipo_Mantenimiento = Column(Integer, ForeignKey("INV_TIPO_MANTENIMIENTO.TMA_Tipo_Mantenimiento"), nullable=False)

    # Relaciones
    detalles = relationship("DetalleMantenimiento", back_populates="mantenimiento")
    evidencias = relationship("Evidencia", back_populates="mantenimiento")


# ==========================================
# 4. DETALLE MANTENIMIENTO (Items)
# ==========================================
class DetalleMantenimiento(Base):
    __tablename__ = "INV_DETALLE_MANT"

    # CORRECCIÓN: Nombre Completo según diccionario
    DMA_Detalle_Mant = Column(Integer, primary_key=True, index=True, autoincrement=True)
    
    DMA_Accion_Realizada = Column(String(255), nullable=False)
    DMA_Costo_Item = Column(Numeric(10, 2), default=0)

    # FK corregida apuntando a MAN_Mantenimiento
    MAN_Mantenimiento = Column(UUID(as_uuid=True), ForeignKey("INV_MANTENIMIENTO.MAN_Mantenimiento"), nullable=False)
    
    mantenimiento = relationship("Mantenimiento", back_populates="detalles")


# ==========================================
# 5. EVIDENCIA (Archivos)
# ==========================================
class Evidencia(Base):
    __tablename__ = "INV_EVIDENCIA"

    EVI_Evidencia = Column(Integer, primary_key=True, index=True, autoincrement=True)
    EVI_URL_Archivo = Column(String(255), nullable=False)
    EVI_Nombre_Archivo = Column(String(100), nullable=True)
    EVI_Tipo_MIME = Column(String(50), nullable=True)

    # FKs Opcionales (XOR Lógico) con nombres completos
    MOV_Movimiento_Ref = Column(UUID(as_uuid=True), ForeignKey("INV_MOVIMIENTO.MOV_Movimiento"), nullable=True)
    MAN_Mantenimiento_Ref = Column(UUID(as_uuid=True), ForeignKey("INV_MANTENIMIENTO.MAN_Mantenimiento"), nullable=True)
    
    TEV_Tipo_Evidencia = Column(Integer, ForeignKey("INV_TIPO_EVIDENCIA.TEV_Tipo_Evidencia"), nullable=False)

    movimiento = relationship("Movimiento", back_populates="evidencias")
    mantenimiento = relationship("Mantenimiento", back_populates="evidencias")