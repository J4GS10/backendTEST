"""
Modelo de Adjuntos: archivos asociados a un activo o a una orden de compra
(factura, foto, acta firmada escaneada, etc.). Los bytes viven en disco
(volumen local); en la BD solo se guardan los metadatos y la ruta.

Un adjunto pertenece a EXACTAMENTE un dueño: un activo (ACT_Activo) o una orden
de compra (OCO_Orden) — invariante reforzada por un CHECK XOR a nivel BD.
"""
import uuid
from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Uuid, func, CheckConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class Adjunto(Base):
    __tablename__ = "INV_ADJUNTO"

    ADJ_Adjunto = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)

    ADJ_Nombre_Original = Column(String(255), nullable=False)
    # Nombre con que se guardó en disco (uuid + extensión) — evita colisiones y
    # path traversal a partir del nombre que envía el cliente.
    ADJ_Nombre_Almacenado = Column(String(255), nullable=False)
    ADJ_Tipo_MIME = Column(String(120), nullable=True)
    ADJ_Tamano_Bytes = Column(Integer, nullable=False)
    # factura | foto | acta | otro
    ADJ_Categoria = Column(String(20), nullable=False, default="otro")
    ADJ_Descripcion = Column(String(255), nullable=True)
    ADJ_Fecha_Subida = Column(DateTime, server_default=func.now(), nullable=False, index=True)

    # Dueño: exactamente uno de los dos (XOR, ver CheckConstraint).
    ACT_Activo = Column(
        Uuid,
        ForeignKey("INV_ACTIVO.ACT_Activo", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    OCO_Orden = Column(
        Integer,
        ForeignKey("INV_ORDEN_COMPRA.OCO_Orden", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    USU_Usuario = Column(
        Uuid,
        ForeignKey("INV_USUARIO.USU_Usuario", ondelete="SET NULL"),
        nullable=True,
    )

    activo = relationship("app.models.core.Activo", backref="adjuntos")

    __table_args__ = (
        CheckConstraint(
            "\"ADJ_Categoria\" IN ('factura', 'foto', 'acta', 'otro')",
            name="ck_adjunto_categoria_valida",
        ),
        CheckConstraint('"ADJ_Tamano_Bytes" >= 0', name="ck_adjunto_tamano_no_negativo"),
        # XOR: exactamente un dueño (activo u orden), nunca ambos ni ninguno.
        CheckConstraint(
            '("ACT_Activo" IS NOT NULL AND "OCO_Orden" IS NULL) '
            'OR ("ACT_Activo" IS NULL AND "OCO_Orden" IS NOT NULL)',
            name="ck_adjunto_un_solo_dueno",
        ),
    )
