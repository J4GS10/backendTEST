import uuid
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Date, Boolean, Uuid,
    CheckConstraint, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.db.base import Base


# ==========================================
# 1. TIPO DE LICENCIA
# ==========================================
class TipoLicencia(Base):
    __tablename__ = "INV_TIPO_LICENCIA"

    TLI_Tipo_Licencia = Column(Integer, primary_key=True, index=True, autoincrement=True)
    TLI_Nombre = Column(String(50), unique=True, nullable=False)
    TLI_Descripcion = Column(String(200), nullable=True)

    licencias = relationship("Licencia", back_populates="tipo_licencia")


# ==========================================
# 2. SOFTWARE
# ==========================================
class Software(Base):
    __tablename__ = "INV_SOFTWARE"

    SOF_Software = Column(Integer, primary_key=True, index=True, autoincrement=True)
    SOF_Nombre = Column(String(100), nullable=False)
    SOF_Version = Column(String(50), nullable=True)
    SOF_Fabricante = Column(String(100), nullable=False)

    licencias = relationship("Licencia", back_populates="software")

    __table_args__ = (
        UniqueConstraint(
            "SOF_Nombre", "SOF_Version", "SOF_Fabricante", name="uq_software_nombre_version_fabr"
        ),
    )


# ==========================================
# 3. LICENCIA
# ==========================================
class Licencia(Base):
    __tablename__ = "INV_LICENCIA"

    LIC_Licencia = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Cifrar en lógica de negocio con cryptography.fernet (FIELD_ENCRYPTION_KEY).
    LIC_Clave_Activacion = Column(String(500), nullable=True)
    LIC_Fecha_Vencimiento = Column(Date, nullable=True)
    LIC_Cantidad_Total = Column(Integer, default=1, nullable=False)
    LIC_Cantidad_Usada = Column(Integer, default=0, nullable=False)

    SOF_Software = Column(
        Integer,
        ForeignKey("INV_SOFTWARE.SOF_Software", ondelete="RESTRICT"),
        nullable=False,
    )
    TLI_Tipo_Licencia = Column(
        Integer,
        ForeignKey("INV_TIPO_LICENCIA.TLI_Tipo_Licencia", ondelete="RESTRICT"),
        nullable=False,
    )

    software = relationship("Software", back_populates="licencias")
    tipo_licencia = relationship("TipoLicencia", back_populates="licencias")
    instalaciones = relationship("Instalacion", back_populates="licencia")

    __table_args__ = (
        CheckConstraint(
            '"LIC_Cantidad_Total" > 0', name="ck_licencia_total_positivo"
        ),
        CheckConstraint(
            '"LIC_Cantidad_Usada" >= 0 AND "LIC_Cantidad_Usada" <= "LIC_Cantidad_Total"',
            name="ck_licencia_usada_valida",
        ),
    )


# ==========================================
# 4. INSTALACIÓN
# ==========================================
class Instalacion(Base):
    __tablename__ = "INV_INSTALACION"

    INS_Instalacion = Column(Integer, primary_key=True, index=True, autoincrement=True)
    INS_Fecha_Instalacion = Column(Date, nullable=False)
    INS_Estado = Column(Boolean, default=True, nullable=False)

    ACT_Activo = Column(
        Uuid,
        ForeignKey("INV_ACTIVO.ACT_Activo", ondelete="CASCADE"),
        nullable=False,
    )
    LIC_Licencia = Column(
        Integer,
        ForeignKey("INV_LICENCIA.LIC_Licencia", ondelete="RESTRICT"),
        nullable=False,
    )

    activo = relationship("app.models.core.Activo", backref="instalaciones")
    licencia = relationship("Licencia", back_populates="instalaciones")
