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

class MarcaResponse(MarcaBase):
    MAR_Marca: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# 3. TIPO DE CONEXIÓN
# =======================
class TipoConexionBase(BaseModel):
    TCN_Nombre: str = Field(..., min_length=2, max_length=50)
    TCN_Descripcion: Optional[str] = None

class TipoConexionCreate(TipoConexionBase):
    pass

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

class ModeloCreate(ModeloBase):
    pass

class ModeloResponse(ModeloBase):
    MOD_Modelo: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# 5. ESTADO OPERATIVO
# =======================
class EstadoOperativoBase(BaseModel):
    EOP_Nombre: str = Field(..., min_length=2, max_length=50)
    EOP_Descripcion: Optional[str] = None

class EstadoOperativoCreate(EstadoOperativoBase):
    pass

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

class TipoEspecificacionResponse(TipoEspecificacionBase):
    TES_Tipo_Especificacion: int
    model_config = ConfigDict(from_attributes=True)