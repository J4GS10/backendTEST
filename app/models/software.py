import uuid
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Date, DateTime, Boolean, Uuid,
    CheckConstraint, UniqueConstraint, Index, func,
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
    claves = relationship(
        "LicenciaClave",
        back_populates="licencia",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

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
class LicenciaClave(Base):
    __tablename__ = "INV_LICENCIA_CLAVE"

    LCL_Licencia_Clave = Column(Integer, primary_key=True, index=True, autoincrement=True)
    LIC_Licencia = Column(
        Integer,
        ForeignKey("INV_LICENCIA.LIC_Licencia", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    LCL_Clave_Activacion = Column(String(1000), nullable=False)
    LCL_Clave_Hash = Column(String(64), nullable=False)
    LCL_Referencia = Column(String(120), nullable=True)
    LCL_Estado = Column(String(20), nullable=False, default="DISPONIBLE")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    licencia = relationship("Licencia", back_populates="claves")
    instalaciones = relationship("Instalacion", back_populates="licencia_clave")

    __table_args__ = (
        UniqueConstraint("LCL_Clave_Hash", name="uq_licencia_clave_hash"),
        CheckConstraint(
            "\"LCL_Estado\" IN ('DISPONIBLE', 'ASIGNADA', 'RETIRADA')",
            name="ck_licencia_clave_estado_valido",
        ),
    )


class Instalacion(Base):
    __tablename__ = "INV_INSTALACION"

    INS_Instalacion = Column(Integer, primary_key=True, index=True, autoincrement=True)
    INS_Fecha_Instalacion = Column(Date, nullable=False)
    INS_Estado = Column(Boolean, default=True, nullable=False)

    ACT_Activo = Column(
        Uuid,
        ForeignKey("INV_ACTIVO.ACT_Activo", ondelete="CASCADE"),
        nullable=True,
    )
    PER_Persona = Column(
        Uuid,
        ForeignKey("INV_PERSONA.PER_Persona", ondelete="CASCADE"),
        nullable=True,
    )
    LIC_Licencia = Column(
        Integer,
        ForeignKey("INV_LICENCIA.LIC_Licencia", ondelete="RESTRICT"),
        nullable=False,
    )
    LCL_Licencia_Clave = Column(
        Integer,
        ForeignKey("INV_LICENCIA_CLAVE.LCL_Licencia_Clave", ondelete="SET NULL"),
        nullable=True,
    )

    activo = relationship("app.models.core.Activo", backref="instalaciones")
    persona = relationship("app.models.organization.Persona", backref="licencias_asignadas")
    licencia = relationship("Licencia", back_populates="instalaciones")
    licencia_clave = relationship("LicenciaClave", back_populates="instalaciones")

    __table_args__ = (
        CheckConstraint(
            '("ACT_Activo" IS NOT NULL AND "PER_Persona" IS NULL) '
            'OR ("ACT_Activo" IS NULL AND "PER_Persona" IS NOT NULL)',
            name="ck_instalacion_destino_xor",
        ),
        Index(
            "uq_instalacion_activo_licencia_activa",
            "ACT_Activo", "LIC_Licencia",
            unique=True,
            postgresql_where=(INS_Estado.is_(True) & ACT_Activo.is_not(None)),
            sqlite_where=(INS_Estado.is_(True) & ACT_Activo.is_not(None)),
        ),
        Index(
            "uq_instalacion_persona_licencia_activa",
            "PER_Persona", "LIC_Licencia",
            unique=True,
            postgresql_where=(INS_Estado.is_(True) & PER_Persona.is_not(None)),
            sqlite_where=(INS_Estado.is_(True) & PER_Persona.is_not(None)),
        ),
        Index(
            "uq_instalacion_clave_activa",
            "LCL_Licencia_Clave",
            unique=True,
            postgresql_where=(INS_Estado.is_(True) & LCL_Licencia_Clave.is_not(None)),
            sqlite_where=(INS_Estado.is_(True) & LCL_Licencia_Clave.is_not(None)),
        ),
    )
