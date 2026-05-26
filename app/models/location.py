from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base import Base


# ==========================================
# 1. PAÍS
# ==========================================
class Pais(Base):
    __tablename__ = "INV_PAIS"

    PAI_Pais = Column(Integer, primary_key=True, index=True, autoincrement=True)
    PAI_Nombre = Column(String(100), nullable=False, unique=True)
    PAI_Codigo_ISO = Column(String(5), nullable=False, unique=True)

    estados = relationship("Estado", back_populates="pais")


# ==========================================
# 2. ESTADO
# ==========================================
class Estado(Base):
    __tablename__ = "INV_ESTADO"

    EST_Estado = Column(Integer, primary_key=True, index=True, autoincrement=True)
    EST_Nombre = Column(String(100), nullable=False)

    PAI_Pais = Column(
        Integer,
        ForeignKey("INV_PAIS.PAI_Pais", ondelete="RESTRICT"),
        nullable=False,
    )

    pais = relationship("Pais", back_populates="estados")
    municipios = relationship("Municipio", back_populates="estado")


# ==========================================
# 3. MUNICIPIO
# ==========================================
class Municipio(Base):
    __tablename__ = "INV_MUNICIPIO"

    MUN_Municipio = Column(Integer, primary_key=True, index=True, autoincrement=True)
    MUN_Nombre = Column(String(100), nullable=False)

    EST_Estado = Column(
        Integer,
        ForeignKey("INV_ESTADO.EST_Estado", ondelete="RESTRICT"),
        nullable=False,
    )

    estado = relationship("Estado", back_populates="municipios")
    sedes = relationship("Sede", back_populates="municipio")


# ==========================================
# 4. SEDE
# ==========================================
class Sede(Base):
    __tablename__ = "INV_SEDE"

    SED_Sede = Column(Integer, primary_key=True, index=True, autoincrement=True)
    SED_Nombre = Column(String(150), nullable=False)
    SED_Direccion_Calle = Column(String(200), nullable=True)
    SED_Direccion_Numero = Column(String(50), nullable=True)

    MUN_Municipio = Column(
        Integer,
        ForeignKey("INV_MUNICIPIO.MUN_Municipio", ondelete="RESTRICT"),
        nullable=False,
    )

    municipio = relationship("Municipio", back_populates="sedes")
    edificios = relationship("Edificio", back_populates="sede")


# ==========================================
# 5. EDIFICIO
# ==========================================
class Edificio(Base):
    __tablename__ = "INV_EDIFICIO"

    EDI_Edificio = Column(Integer, primary_key=True, index=True, autoincrement=True)
    EDI_Nombre = Column(String(100), nullable=False)

    SED_Sede = Column(
        Integer,
        ForeignKey("INV_SEDE.SED_Sede", ondelete="RESTRICT"),
        nullable=False,
    )

    sede = relationship("Sede", back_populates="edificios")
    niveles = relationship("Nivel", back_populates="edificio")


# ==========================================
# 6. NIVEL
# ==========================================
class Nivel(Base):
    __tablename__ = "INV_NIVEL"

    NIV_Nivel = Column(Integer, primary_key=True, index=True, autoincrement=True)
    NIV_Numero_Piso = Column(String(50), nullable=False)
    NIV_Alias = Column(String(100), nullable=True)

    EDI_Edificio = Column(
        Integer,
        ForeignKey("INV_EDIFICIO.EDI_Edificio", ondelete="RESTRICT"),
        nullable=False,
    )

    edificio = relationship("Edificio", back_populates="niveles")
    areas = relationship("Area", back_populates="nivel")


# ==========================================
# 7. ÁREA
# ==========================================
class Area(Base):
    __tablename__ = "INV_AREA"

    ARE_Area = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ARE_Nombre = Column(String(150), nullable=False)
    ARE_Tipo_Acceso = Column(String(50), default="General", nullable=False)
    ARE_Descripcion = Column(String(255), nullable=True)

    NIV_Nivel = Column(
        Integer,
        ForeignKey("INV_NIVEL.NIV_Nivel", ondelete="RESTRICT"),
        nullable=False,
    )

    nivel = relationship("Nivel", back_populates="areas")
