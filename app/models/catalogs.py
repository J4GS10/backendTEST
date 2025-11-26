from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.db.base import Base

# ==========================================
# 1. TIPO DE ACTIVO
# ==========================================
class TipoActivo(Base):
    __tablename__ = "INV_TIPO_ACTIVO"

    TAC_Tipo_Activo = Column(Integer, primary_key=True, index=True, autoincrement=True)
    TAC_Nombre = Column(String(100), unique=True, nullable=False) 
    TAC_Aplica_Depreciacion = Column(Boolean, default=True)

    # CORRECCIÓN: Usamos path completo para evitar error de importación
    activos = relationship("app.models.core.Activo", back_populates="tipo_activo")


# ==========================================
# 2. MARCA
# ==========================================
class Marca(Base):
    __tablename__ = "INV_MARCA"

    MAR_Marca = Column(Integer, primary_key=True, index=True, autoincrement=True)
    MAR_Nombre = Column(String(100), unique=True, nullable=False)

    modelos = relationship("Modelo", back_populates="marca")


# ==========================================
# 3. TIPO DE CONEXIÓN
# ==========================================
class TipoConexion(Base):
    __tablename__ = "INV_TIPO_CONEXION"

    TCN_Tipo_Conexion = Column(Integer, primary_key=True, index=True, autoincrement=True)
    TCN_Nombre = Column(String(50), unique=True, nullable=False)
    TCN_Descripcion = Column(String(200), nullable=True)

    modelos = relationship("Modelo", back_populates="tipo_conexion")


# ==========================================
# 4. MODELO
# ==========================================
class Modelo(Base):
    __tablename__ = "INV_MODELO"

    MOD_Modelo = Column(Integer, primary_key=True, index=True, autoincrement=True)
    MOD_Nombre = Column(String(150), nullable=False)
    MOD_Anio_Lanzamiento = Column(Integer, nullable=True)

    MAR_Marca = Column(Integer, ForeignKey("INV_MARCA.MAR_Marca"), nullable=False)
    TCN_Tipo_Conexion = Column(Integer, ForeignKey("INV_TIPO_CONEXION.TCN_Tipo_Conexion"), nullable=True)

    marca = relationship("Marca", back_populates="modelos")
    tipo_conexion = relationship("TipoConexion", back_populates="modelos")
    
    # CORRECCIÓN: Path completo
    activos = relationship("app.models.core.Activo", back_populates="modelo")


# ==========================================
# 5. ESTADO OPERATIVO
# ==========================================
class EstadoOperativo(Base):
    __tablename__ = "INV_ESTADO_OPERATIVO"

    EOP_Estado_Operativo = Column(Integer, primary_key=True, index=True, autoincrement=True)
    EOP_Nombre = Column(String(50), unique=True, nullable=False)
    EOP_Descripcion = Column(String(200), nullable=True)

    # CORRECCIÓN: Path completo
    activos = relationship("app.models.core.Activo", back_populates="estado_operativo")


# ==========================================
# 6. TIPO DE ESPECIFICACIÓN
# ==========================================
class TipoEspecificacion(Base):
    __tablename__ = "INV_TIPO_ESPECIFICACION"

    TES_Tipo_Especificacion = Column(Integer, primary_key=True, index=True, autoincrement=True)
    TES_Nombre = Column(String(100), unique=True, nullable=False)
    TES_Unidad_Medida = Column(String(20), nullable=True)

    especificaciones = relationship("app.models.core.Especificacion", back_populates="tipo_especificacion")