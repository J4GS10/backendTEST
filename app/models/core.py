import uuid
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Date, Numeric, Uuid,
    CheckConstraint, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from app.db.base import Base


# ==========================================
# 1. ACTIVO
# ==========================================
class Activo(Base):
    __tablename__ = "INV_ACTIVO"

    ACT_Activo = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)

    ACT_Codigo_Interno = Column(String(50), unique=True, nullable=False, index=True)
    ACT_Serie_Fabricante = Column(String(100), nullable=False)
    ACT_Hostname = Column(String(100), nullable=True)

    ACT_Fecha_Compra = Column(Date, nullable=False)
    ACT_Fin_Garantia = Column(Date, nullable=True)
    ACT_Costo = Column(Numeric(12, 2), nullable=True)

    MOD_Modelo = Column(
        Integer,
        ForeignKey("INV_MODELO.MOD_Modelo", ondelete="RESTRICT"),
        nullable=False,
    )
    TAC_Tipo_Activo = Column(
        Integer,
        ForeignKey("INV_TIPO_ACTIVO.TAC_Tipo_Activo", ondelete="RESTRICT"),
        nullable=False,
    )
    EOP_Estado_Operativo = Column(
        Integer,
        ForeignKey("INV_ESTADO_OPERATIVO.EOP_Estado_Operativo", ondelete="RESTRICT"),
        nullable=False,
    )

    ACT_Activo_Padre = Column(
        Uuid,
        ForeignKey("INV_ACTIVO.ACT_Activo", ondelete="SET NULL"),
        nullable=True,
    )

    modelo = relationship("app.models.catalogs.Modelo", back_populates="activos")
    tipo_activo = relationship("app.models.catalogs.TipoActivo", back_populates="activos")
    estado_operativo = relationship("app.models.catalogs.EstadoOperativo", back_populates="activos")

    hijos = relationship("Activo", backref="padre", remote_side=[ACT_Activo])
    especificaciones = relationship(
        "Especificacion", back_populates="activo", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("ACT_Serie_Fabricante", name="uq_activo_serie_fabricante"),
        CheckConstraint(
            '"ACT_Fin_Garantia" IS NULL OR "ACT_Fin_Garantia" >= "ACT_Fecha_Compra"',
            name="ck_activo_garantia_posterior_compra",
        ),
        CheckConstraint(
            '"ACT_Activo_Padre" IS NULL OR "ACT_Activo_Padre" <> "ACT_Activo"',
            name="ck_activo_padre_distinto_self",
        ),
        CheckConstraint(
            '"ACT_Costo" IS NULL OR "ACT_Costo" >= 0',
            name="ck_activo_costo_no_negativo",
        ),
        Index("ix_activo_hostname", "ACT_Hostname"),
    )


# ==========================================
# 2. ESPECIFICACIONES TÉCNICAS
# ==========================================
class Especificacion(Base):
    __tablename__ = "INV_ESPECIFICACION"

    ESP_Especificacion = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ESP_Valor = Column(String(255), nullable=False)

    ACT_Activo = Column(
        Uuid,
        ForeignKey("INV_ACTIVO.ACT_Activo", ondelete="CASCADE"),
        nullable=False,
    )
    TES_Tipo_Especificacion = Column(
        Integer,
        ForeignKey("INV_TIPO_ESPECIFICACION.TES_Tipo_Especificacion", ondelete="RESTRICT"),
        nullable=False,
    )

    activo = relationship("Activo", back_populates="especificaciones")
    tipo_especificacion = relationship(
        "app.models.catalogs.TipoEspecificacion", back_populates="especificaciones"
    )

    __table_args__ = (
        UniqueConstraint(
            "ACT_Activo", "TES_Tipo_Especificacion", name="uq_espec_activo_tipo"
        ),
    )
