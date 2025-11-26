from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.db.base import Base

# ==========================================
# 1. NIVEL: PAÍS
# ==========================================
class Pais(Base):
    __tablename__ = "INV_PAIS"

    PAI_Pais = Column(Integer, primary_key=True, index=True, autoincrement=True)
    PAI_Nombre = Column(String(100), nullable=False, unique=True)
    PAI_Codigo_ISO = Column(String(5), nullable=False, unique=True) # Ej: GT, MX

    # Relación: Un País -> Muchos Estados
    estados = relationship("Estado", back_populates="pais")


# ==========================================
# 2. NIVEL: ESTADO (Departamento/Provincia)
# ==========================================
class Estado(Base):
    __tablename__ = "INV_ESTADO"

    EST_Estado = Column(Integer, primary_key=True, index=True, autoincrement=True)
    EST_Nombre = Column(String(100), nullable=False)
    
    # FK
    PAI_Pais = Column(Integer, ForeignKey("INV_PAIS.PAI_Pais"), nullable=False)

    # Relaciones
    pais = relationship("Pais", back_populates="estados")
    municipios = relationship("Municipio", back_populates="estado")


# ==========================================
# 3. NIVEL: MUNICIPIO
# ==========================================
class Municipio(Base):
    __tablename__ = "INV_MUNICIPIO"

    MUN_Municipio = Column(Integer, primary_key=True, index=True, autoincrement=True)
    MUN_Nombre = Column(String(100), nullable=False)
    
    # FK
    EST_Estado = Column(Integer, ForeignKey("INV_ESTADO.EST_Estado"), nullable=False)

    # Relaciones
    estado = relationship("Estado", back_populates="municipios")
    sedes = relationship("Sede", back_populates="municipio")


# ==========================================
# 4. NIVEL: SEDE (Campus/Edificio Principal)
# ==========================================
class Sede(Base):
    __tablename__ = "INV_SEDE"

    SED_Sede = Column(Integer, primary_key=True, index=True, autoincrement=True)
    SED_Nombre = Column(String(150), nullable=False) # Ej: Campus Central
    SED_Direccion_Calle = Column(String(200), nullable=True)
    SED_Direccion_Numero = Column(String(50), nullable=True)
    
    # FK
    MUN_Municipio = Column(Integer, ForeignKey("INV_MUNICIPIO.MUN_Municipio"), nullable=False)

    # Relaciones
    municipio = relationship("Municipio", back_populates="sedes")
    edificios = relationship("Edificio", back_populates="sede")


# ==========================================
# 5. NIVEL: EDIFICIO (Torre/Bloque)
# ==========================================
class Edificio(Base):
    __tablename__ = "INV_EDIFICIO"

    EDI_Edificio = Column(Integer, primary_key=True, index=True, autoincrement=True)
    EDI_Nombre = Column(String(100), nullable=False) # Ej: Torre A
    
    # FK
    SED_Sede = Column(Integer, ForeignKey("INV_SEDE.SED_Sede"), nullable=False)

    # Relaciones
    sede = relationship("Sede", back_populates="edificios")
    niveles = relationship("Nivel", back_populates="edificio")


# ==========================================
# 6. NIVEL: NIVEL (Piso)
# ==========================================
class Nivel(Base):
    __tablename__ = "INV_NIVEL"

    NIV_Nivel = Column(Integer, primary_key=True, index=True, autoincrement=True)
    NIV_Numero_Piso = Column(String(50), nullable=False) # Ej: "PB", "Piso 1"
    NIV_Alias = Column(String(100), nullable=True) # Ej: "Mezzanine"
    
    # FK
    EDI_Edificio = Column(Integer, ForeignKey("INV_EDIFICIO.EDI_Edificio"), nullable=False)

    # Relaciones
    edificio = relationship("Edificio", back_populates="niveles")
    areas = relationship("Area", back_populates="nivel")


# ==========================================
# 7. NIVEL: ÁREA (Oficina Final)
# ==========================================
class Area(Base):
    __tablename__ = "INV_AREA"

    ARE_Area = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ARE_Nombre = Column(String(150), nullable=False) # Ej: "Site de Servidores", "Oficina 305"
    ARE_Tipo_Acceso = Column(String(50), default="General") # Ej: Restringido, Público
    ARE_Descripcion = Column(String(255), nullable=True)
    
    # FK
    NIV_Nivel = Column(Integer, ForeignKey("INV_NIVEL.NIV_Nivel"), nullable=False)

    # Relaciones
    nivel = relationship("Nivel", back_populates="areas")
    # movimientos = relationship("Movimiento", back_populates="area") # Se habilitará en el futuro