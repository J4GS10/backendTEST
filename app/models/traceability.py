import uuid
from sqlalchemy import (
    Column, Integer, String, ForeignKey, DateTime, Text, Numeric, func, Uuid,
    CheckConstraint, Index,
)
from sqlalchemy.orm import relationship
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

    MOV_Movimiento = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)

    MOV_Fecha_Asignacion = Column(DateTime, server_default=func.now(), nullable=False)
    MOV_Fecha_Devolucion = Column(DateTime, nullable=True)
    MOV_Observacion = Column(Text, nullable=True)

    ACT_Activo = Column(
        Uuid,
        ForeignKey("INV_ACTIVO.ACT_Activo", ondelete="RESTRICT"),
        nullable=False,
    )
    PER_Persona = Column(
        Uuid,
        ForeignKey("INV_PERSONA.PER_Persona", ondelete="RESTRICT"),
        nullable=False,
    )
    ARE_Area = Column(
        Integer,
        ForeignKey("INV_AREA.ARE_Area", ondelete="RESTRICT"),
        nullable=False,
    )
    TMO_Tipo_Movimiento = Column(
        Integer,
        ForeignKey("INV_TIPO_MOVIMIENTO.TMO_Tipo_Movimiento", ondelete="RESTRICT"),
        nullable=False,
    )

    activo = relationship("app.models.core.Activo", backref="movimientos")
    persona = relationship("app.models.organization.Persona", backref="movimientos")
    area = relationship("app.models.location.Area")
    tipo_movimiento = relationship("TipoMovimiento")

    evidencias = relationship(
        "Evidencia", back_populates="movimiento", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            '"MOV_Fecha_Devolucion" IS NULL OR "MOV_Fecha_Devolucion" >= "MOV_Fecha_Asignacion"',
            name="ck_movimiento_devolucion_posterior",
        ),
        # Índice parcial UNIQUE: solo un movimiento abierto por activo.
        # Postgres y SQLite >= 3.8 lo soportan.
        Index(
            "uq_movimiento_activo_abierto",
            "ACT_Activo",
            unique=True,
            postgresql_where=(MOV_Fecha_Devolucion.is_(None)),
            sqlite_where=(MOV_Fecha_Devolucion.is_(None)),
        ),
        Index("ix_movimiento_persona", "PER_Persona"),
        Index("ix_movimiento_area", "ARE_Area"),
        # Índice general por activo: acelera el historial completo (todos los
        # movimientos de un activo, no solo el vigente que cubre el índice parcial).
        Index("ix_movimiento_activo", "ACT_Activo"),
    )


# ==========================================
# 3. MANTENIMIENTO (Tickets)
# ==========================================
class Mantenimiento(Base):
    __tablename__ = "INV_MANTENIMIENTO"

    MAN_Mantenimiento = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)

    MAN_Fecha_Ingreso = Column(DateTime, server_default=func.now(), nullable=False)
    MAN_Fecha_Cierre = Column(DateTime, nullable=True)
    MAN_Descripcion_Falla = Column(Text, nullable=False)
    MAN_Costo_Total = Column(Numeric(12, 2), default=0, nullable=False)

    ACT_Activo = Column(
        Uuid,
        ForeignKey("INV_ACTIVO.ACT_Activo", ondelete="RESTRICT"),
        nullable=False,
    )
    PER_Persona_Solicita = Column(
        Uuid,
        ForeignKey("INV_PERSONA.PER_Persona", ondelete="RESTRICT"),
        nullable=False,
    )
    TMA_Tipo_Mantenimiento = Column(
        Integer,
        ForeignKey("INV_TIPO_MANTENIMIENTO.TMA_Tipo_Mantenimiento", ondelete="RESTRICT"),
        nullable=False,
    )

    activo = relationship("app.models.core.Activo")
    persona_solicita = relationship("app.models.organization.Persona", foreign_keys=[PER_Persona_Solicita])
    tipo_mantenimiento = relationship("TipoMantenimiento")
    detalles = relationship(
        "DetalleMantenimiento", back_populates="mantenimiento", cascade="all, delete-orphan"
    )
    evidencias = relationship(
        "Evidencia", back_populates="mantenimiento", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            '"MAN_Fecha_Cierre" IS NULL OR "MAN_Fecha_Cierre" >= "MAN_Fecha_Ingreso"',
            name="ck_mantenimiento_cierre_posterior",
        ),
        CheckConstraint(
            '"MAN_Costo_Total" >= 0', name="ck_mantenimiento_costo_no_negativo"
        ),
        # Índice parcial UNIQUE: solo un mantenimiento ABIERTO por activo
        # (garantía de concurrencia a nivel BD, espejo del de INV_MOVIMIENTO).
        Index(
            "uq_mantenimiento_activo_abierto",
            "ACT_Activo",
            unique=True,
            postgresql_where=(MAN_Fecha_Cierre.is_(None)),
            sqlite_where=(MAN_Fecha_Cierre.is_(None)),
        ),
        Index("ix_mantenimiento_activo", "ACT_Activo"),
    )


# ==========================================
# 4. DETALLE MANTENIMIENTO
# ==========================================
class DetalleMantenimiento(Base):
    __tablename__ = "INV_DETALLE_MANT"

    DMA_Detalle_Mant = Column(Integer, primary_key=True, index=True, autoincrement=True)
    DMA_Accion_Realizada = Column(String(255), nullable=False)
    DMA_Costo_Item = Column(Numeric(12, 2), default=0, nullable=False)

    MAN_Mantenimiento = Column(
        Uuid,
        ForeignKey("INV_MANTENIMIENTO.MAN_Mantenimiento", ondelete="CASCADE"),
        nullable=False,
    )

    mantenimiento = relationship("Mantenimiento", back_populates="detalles")

    __table_args__ = (
        CheckConstraint(
            '"DMA_Costo_Item" >= 0', name="ck_detalle_costo_no_negativo"
        ),
    )


# ==========================================
# 5. EVIDENCIA (XOR: pertenece a Movimiento O a Mantenimiento, no ambos)
# ==========================================
class Evidencia(Base):
    __tablename__ = "INV_EVIDENCIA"

    EVI_Evidencia = Column(Integer, primary_key=True, index=True, autoincrement=True)
    EVI_URL_Archivo = Column(String(500), nullable=False)
    EVI_Nombre_Archivo = Column(String(150), nullable=True)
    EVI_Tipo_MIME = Column(String(100), nullable=True)

    MOV_Movimiento_Ref = Column(
        Uuid,
        ForeignKey("INV_MOVIMIENTO.MOV_Movimiento", ondelete="CASCADE"),
        nullable=True,
    )
    MAN_Mantenimiento_Ref = Column(
        Uuid,
        ForeignKey("INV_MANTENIMIENTO.MAN_Mantenimiento", ondelete="CASCADE"),
        nullable=True,
    )

    TEV_Tipo_Evidencia = Column(
        Integer,
        ForeignKey("INV_TIPO_EVIDENCIA.TEV_Tipo_Evidencia", ondelete="RESTRICT"),
        nullable=False,
    )

    movimiento = relationship("Movimiento", back_populates="evidencias")
    mantenimiento = relationship("Mantenimiento", back_populates="evidencias")

    __table_args__ = (
        # XOR: exactamente uno de los dos refs no nulo.
        CheckConstraint(
            '("MOV_Movimiento_Ref" IS NOT NULL AND "MAN_Mantenimiento_Ref" IS NULL) '
            'OR ("MOV_Movimiento_Ref" IS NULL AND "MAN_Mantenimiento_Ref" IS NOT NULL)',
            name="ck_evidencia_xor_movimiento_mantenimiento",
        ),
    )
