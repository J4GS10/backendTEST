from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

# =======================
# 1. TIPO DE ACTIVO
# =======================
class TipoActivoBase(BaseModel):
    TAC_Nombre: str = Field(..., min_length=2, max_length=100)
    TAC_Prefijo: Optional[str] = Field(None, max_length=10)
    TAC_Aplica_Depreciacion: bool = True

class TipoActivoCreate(TipoActivoBase):
    pass

class TipoActivoUpdate(BaseModel):
    TAC_Nombre: Optional[str] = Field(None, min_length=2, max_length=100)
    TAC_Prefijo: Optional[str] = Field(None, max_length=10)
    TAC_Aplica_Depreciacion: Optional[bool] = None


class TipoActivoResponse(TipoActivoBase):
    TAC_Tipo_Activo: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# 2. MARCA
# =======================
class MarcaBase(BaseModel):
    MAR_Nombre: str = Field(..., min_length=2, max_length=100)

class MarcaCreate(MarcaBase):
    pass

class MarcaUpdate(BaseModel):
    MAR_Nombre: Optional[str] = Field(None, min_length=2, max_length=100)


class MarcaResponse(MarcaBase):
    MAR_Marca: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# 3. TIPO DE CONEXIÓN
# =======================
class TipoConexionBase(BaseModel):
    TCN_Nombre: str = Field(..., min_length=2, max_length=50)
    TCN_Descripcion: Optional[str] = Field(None, max_length=200)

class TipoConexionCreate(TipoConexionBase):
    pass

class TipoConexionUpdate(BaseModel):
    TCN_Nombre: Optional[str] = Field(None, min_length=2, max_length=50)
    TCN_Descripcion: Optional[str] = Field(None, max_length=200)


class TipoConexionResponse(TipoConexionBase):
    TCN_Tipo_Conexion: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# 4. MODELO
# =======================
class ModeloBase(BaseModel):
    MOD_Nombre: str = Field(..., min_length=2, max_length=150)
    MOD_Anio_Lanzamiento: Optional[int] = None
    
    # FKs
    MAR_Marca: int
    TCN_Tipo_Conexion: Optional[int] = None
    TAC_Tipo_Activo: Optional[int] = None

class ModeloCreate(ModeloBase):
    # Cota de rango SOLO en la entrada (la base/respuesta quedan laxas para no
    # romper la serialización de modelos legados con años fuera de rango).
    MOD_Anio_Lanzamiento: Optional[int] = Field(None, ge=1970, le=2100)

class ModeloUpdate(BaseModel):
    MOD_Nombre: Optional[str] = Field(None, min_length=2, max_length=150)
    MOD_Anio_Lanzamiento: Optional[int] = Field(None, ge=1970, le=2100)
    MAR_Marca: Optional[int] = None
    TCN_Tipo_Conexion: Optional[int] = None
    TAC_Tipo_Activo: Optional[int] = None


class ModeloResponse(ModeloBase):
    MOD_Modelo: int
    model_config = ConfigDict(from_attributes=True)


class ModeloFlatResponse(BaseModel):
    """Modelo con marca embebida (plano), pensado para selects del frontend."""
    MOD_Modelo: int
    MOD_Nombre: str
    MAR_Marca: int
    MAR_Nombre: str
    TCN_Tipo_Conexion: Optional[int] = None
    TAC_Tipo_Activo: Optional[int] = None
    MOD_Anio_Lanzamiento: Optional[int] = None

    @property
    def label(self) -> str:
        return f"{self.MAR_Nombre} {self.MOD_Nombre}"

    model_config = ConfigDict(from_attributes=True)

# =======================
# 5. ESTADO OPERATIVO
# =======================
class EstadoOperativoBase(BaseModel):
    EOP_Nombre: str = Field(..., min_length=2, max_length=50)
    EOP_Descripcion: Optional[str] = Field(None, max_length=200)

class EstadoOperativoCreate(EstadoOperativoBase):
    pass

class EstadoOperativoUpdate(BaseModel):
    EOP_Nombre: Optional[str] = Field(None, min_length=2, max_length=50)
    EOP_Descripcion: Optional[str] = Field(None, max_length=200)


class EstadoOperativoResponse(EstadoOperativoBase):
    EOP_Estado_Operativo: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# 6. TIPO DE ESPECIFICACIÓN (EAV Keys)
# =======================
class TipoEspecificacionBase(BaseModel):
    TES_Nombre: str = Field(..., min_length=2, max_length=100, description="Ej: RAM, Disco Duro")
    TES_Unidad_Medida: Optional[str] = Field(None, max_length=20, description="Ej: GB, TB, GHz")

class TipoEspecificacionCreate(TipoEspecificacionBase):
    pass

class TipoEspecificacionUpdate(BaseModel):
    TES_Nombre: Optional[str] = Field(None, min_length=2, max_length=100)
    TES_Unidad_Medida: Optional[str] = Field(None, max_length=20)


class TipoEspecificacionResponse(TipoEspecificacionBase):
    TES_Tipo_Especificacion: int
    model_config = ConfigDict(from_attributes=True)