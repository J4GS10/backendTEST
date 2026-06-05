"""
Modelo de Compras: Proveedores y Órdenes de Compra (con líneas).

Diseño no invasivo: una línea de orden puede enlazar opcionalmente a un activo
(ACT_Activo) o a un consumible (CON_Consumible). Así la garantía de un activo
deriva su proveedor a través de la orden, sin modificar INV_ACTIVO.
"""
import uuid
from sqlalchemy import (
    Column, Integer, String, Boolean, Date, DateTime, ForeignKey, Numeric, Uuid,
    func, CheckConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


# ==========================================
# 1. PROVEEDOR
# ==========================================
class Proveedor(Base):
    __tablename__ = "INV_PROVEEDOR"

    PRV_Proveedor = Column(Integer, primary_key=True, index=True, autoincrement=True)

    PRV_Nombre = Column(String(150), nullable=False, unique=True)
    PRV_Identificacion_Fiscal = Column(String(50), nullable=True)  # NIT / RFC / RUC
    PRV_Contacto = Column(String(100), nullable=True)
    PRV_Email = Column(String(150), nullable=True)
    PRV_Telefono = Column(String(30), nullable=True)
    PRV_Direccion = Column(String(255), nullable=True)
    PRV_Activo = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())

    ordenes = relationship("OrdenCompra", back_populates="proveedor")


# ==========================================
# 2. ORDEN DE COMPRA
# ==========================================
class OrdenCompra(Base):
    __tablename__ = "INV_ORDEN_COMPRA"

    OCO_Orden = Column(Integer, primary_key=True, index=True, autoincrement=True)

    OCO_Numero = Column(String(50), nullable=False, unique=True)
    OCO_Fecha = Column(Date, nullable=False)
    # BORRADOR -> RECIBIDA | CANCELADA
    OCO_Estado = Column(String(15), nullable=False, default="BORRADOR")
    OCO_Moneda = Column(String(3), nullable=False, default="USD")
    OCO_Total = Column(Numeric(14, 2), nullable=False, default=0)
    OCO_Notas = Column(String(500), nullable=True)

    PRV_Proveedor = Column(
        Integer,
        ForeignKey("INV_PROVEEDOR.PRV_Proveedor", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    USU_Usuario = Column(
        Uuid,
        ForeignKey("INV_USUARIO.USU_Usuario", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    proveedor = relationship("Proveedor", back_populates="ordenes")
    lineas = relationship(
        "OrdenCompraLinea", back_populates="orden", cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "\"OCO_Estado\" IN ('BORRADOR', 'RECIBIDA', 'CANCELADA')",
            name="ck_orden_estado_valido",
        ),
        CheckConstraint('"OCO_Total" >= 0', name="ck_orden_total_no_negativo"),
    )


# ==========================================
# 3. LÍNEA DE ORDEN DE COMPRA
# ==========================================
class OrdenCompraLinea(Base):
    __tablename__ = "INV_ORDEN_COMPRA_LINEA"

    OCL_Linea = Column(Integer, primary_key=True, index=True, autoincrement=True)

    OCL_Descripcion = Column(String(255), nullable=False)
    OCL_Cantidad = Column(Integer, nullable=False, default=1)
    OCL_Precio_Unitario = Column(Numeric(14, 2), nullable=False, default=0)
    OCL_Subtotal = Column(Numeric(14, 2), nullable=False, default=0)

    OCO_Orden = Column(
        Integer,
        ForeignKey("INV_ORDEN_COMPRA.OCO_Orden", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Enlace opcional al activo o consumible adquirido (alimenta garantías).
    ACT_Activo = Column(
        Uuid,
        ForeignKey("INV_ACTIVO.ACT_Activo", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    CON_Consumible = Column(
        Integer,
        ForeignKey("INV_CONSUMIBLE.CON_Consumible", ondelete="SET NULL"),
        nullable=True,
    )

    orden = relationship("OrdenCompra", back_populates="lineas")

    __table_args__ = (
        CheckConstraint('"OCL_Cantidad" > 0', name="ck_linea_cantidad_positiva"),
        CheckConstraint('"OCL_Precio_Unitario" >= 0', name="ck_linea_precio_no_negativo"),
    )
