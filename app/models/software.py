import uuid
from sqlalchemy import Column, Integer, String, ForeignKey, Date, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base

# ==========================================
# 1. TIPO DE LICENCIA (Catálogo)
# ==========================================
class TipoLicencia(Base):
    __tablename__ = "INV_TIPO_LICENCIA"

    TLI_Tipo_Licencia = Column(Integer, primary_key=True, index=True, autoincrement=True)
    TLI_Nombre = Column(String(50), unique=True, nullable=False) # Ej: OEM, Volumen, SaaS
    TLI_Descripcion = Column(String(200), nullable=True)

    licencias = relationship("Licencia", back_populates="tipo_licencia")


# ==========================================
# 2. SOFTWARE (Catálogo)
# ==========================================
class Software(Base):
    __tablename__ = "INV_SOFTWARE"

    SOF_Software = Column(Integer, primary_key=True, index=True, autoincrement=True)
    SOF_Nombre = Column(String(100), nullable=False) # Ej: Office 365
    SOF_Version = Column(String(50), nullable=True)  # Ej: 2024 Enterprise
    SOF_Fabricante = Column(String(100), nullable=False) # Ej: Microsoft

    licencias = relationship("Licencia", back_populates="software")


# ==========================================
# 3. LICENCIA (Inventario Digital)
# ==========================================
class Licencia(Base):
    __tablename__ = "INV_LICENCIA"

    LIC_Licencia = Column(Integer, primary_key=True, index=True, autoincrement=True)
    
    LIC_Clave_Activacion = Column(String(255), nullable=True) # Encriptar en lógica de negocio
    LIC_Fecha_Vencimiento = Column(Date, nullable=True)
    LIC_Cantidad_Total = Column(Integer, default=1)
    LIC_Cantidad_Usada = Column(Integer, default=0)

    # FKs
    SOF_Software = Column(Integer, ForeignKey("INV_SOFTWARE.SOF_Software"), nullable=False)
    TLI_Tipo_Licencia = Column(Integer, ForeignKey("INV_TIPO_LICENCIA.TLI_Tipo_Licencia"), nullable=False)

    # Relaciones
    software = relationship("Software", back_populates="licencias")
    tipo_licencia = relationship("TipoLicencia", back_populates="licencias")
    instalaciones = relationship("Instalacion", back_populates="licencia")


# ==========================================
# 4. INSTALACIÓN (Relación Activo <-> Licencia)
# ==========================================
class Instalacion(Base):
    __tablename__ = "INV_INSTALACION"

    INS_Instalacion = Column(Integer, primary_key=True, index=True, autoincrement=True)
    INS_Fecha_Instalacion = Column(Date, nullable=False)
    INS_Estado = Column(Boolean, default=True) # True = Instalada, False = Desinstalada

    # FKs
    ACT_Activo = Column(UUID(as_uuid=True), ForeignKey("INV_ACTIVO.ACT_Activo"), nullable=False)
    LIC_Licencia = Column(Integer, ForeignKey("INV_LICENCIA.LIC_Licencia"), nullable=False)

    # Relaciones
    activo = relationship("app.models.core.Activo", backref="instalaciones")
    licencia = relationship("Licencia", back_populates="instalaciones")