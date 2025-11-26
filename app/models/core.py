import uuid
from sqlalchemy import Column, Integer, String, ForeignKey, Date, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base

# ==========================================
# 1. EL ACTIVO
# ==========================================
class Activo(Base):
    __tablename__ = "INV_ACTIVO"

    ACT_Activo = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    ACT_Codigo_Interno = Column(String(50), unique=True, nullable=False, index=True)
    ACT_Serie_Fabricante = Column(String(100), nullable=False)
    ACT_Hostname = Column(String(100), nullable=True)
    
    ACT_Fecha_Compra = Column(Date, nullable=False)
    ACT_Fin_Garantia = Column(Date, nullable=True)
    ACT_Costo = Column(Numeric(12, 2), nullable=True)

    # FKs
    MOD_Modelo = Column(Integer, ForeignKey("INV_MODELO.MOD_Modelo"), nullable=False)
    TAC_Tipo_Activo = Column(Integer, ForeignKey("INV_TIPO_ACTIVO.TAC_Tipo_Activo"), nullable=False)
    EOP_Estado_Operativo = Column(Integer, ForeignKey("INV_ESTADO_OPERATIVO.EOP_Estado_Operativo"), nullable=False)
    
    ACT_Activo_Padre = Column(UUID(as_uuid=True), ForeignKey("INV_ACTIVO.ACT_Activo"), nullable=True)

    # RELACIONES CON PATH COMPLETO (Evita error circular)
    modelo = relationship("app.models.catalogs.Modelo", back_populates="activos")
    tipo_activo = relationship("app.models.catalogs.TipoActivo", back_populates="activos")
    estado_operativo = relationship("app.models.catalogs.EstadoOperativo", back_populates="activos")
    
    hijos = relationship("Activo", backref="padre", remote_side=[ACT_Activo])
    
    # Relación local (mismo archivo) se puede llamar directo o con path
    especificaciones = relationship("Especificacion", back_populates="activo")


# ==========================================
# 2. ESPECIFICACIONES TÉCNICAS
# ==========================================
class Especificacion(Base):
    __tablename__ = "INV_ESPECIFICACION"

    ESP_Especificacion = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ESP_Valor = Column(String(255), nullable=False)

    ACT_Activo = Column(UUID(as_uuid=True), ForeignKey("INV_ACTIVO.ACT_Activo"), nullable=False)
    TES_Tipo_Especificacion = Column(Integer, ForeignKey("INV_TIPO_ESPECIFICACION.TES_Tipo_Especificacion"), nullable=False)

    # Relaciones
    activo = relationship("Activo", back_populates="especificaciones")
    
    # Path completo al catálogo
    tipo_especificacion = relationship("app.models.catalogs.TipoEspecificacion", back_populates="especificaciones")