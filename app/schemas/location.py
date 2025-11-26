from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

# =======================
# 1. PAIS
# =======================
class PaisBase(BaseModel):
    PAI_Nombre: str = Field(..., min_length=2, max_length=100)
    PAI_Codigo_ISO: str = Field(..., min_length=2, max_length=5)

class PaisCreate(PaisBase):
    pass

class PaisResponse(PaisBase):
    PAI_Pais: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# 2. ESTADO
# =======================
class EstadoBase(BaseModel):
    EST_Nombre: str = Field(..., min_length=2, max_length=100)
    PAI_Pais: int # FK

class EstadoCreate(EstadoBase):
    pass

class EstadoResponse(EstadoBase):
    EST_Estado: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# 3. MUNICIPIO
# =======================
class MunicipioBase(BaseModel):
    MUN_Nombre: str = Field(..., min_length=2, max_length=100)
    EST_Estado: int # FK

class MunicipioCreate(MunicipioBase):
    pass

class MunicipioResponse(MunicipioBase):
    MUN_Municipio: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# 4. SEDE
# =======================
class SedeBase(BaseModel):
    SED_Nombre: str = Field(..., min_length=3, max_length=150)
    SED_Direccion_Calle: Optional[str] = None
    SED_Direccion_Numero: Optional[str] = None
    MUN_Municipio: int # FK

class SedeCreate(SedeBase):
    pass

class SedeResponse(SedeBase):
    SED_Sede: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# 5. EDIFICIO
# =======================
class EdificioBase(BaseModel):
    EDI_Nombre: str = Field(..., min_length=1, max_length=100)
    SED_Sede: int # FK

class EdificioCreate(EdificioBase):
    pass

class EdificioResponse(EdificioBase):
    EDI_Edificio: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# 6. NIVEL (Piso)
# =======================
class NivelBase(BaseModel):
    NIV_Numero_Piso: str = Field(..., min_length=1, max_length=50)
    NIV_Alias: Optional[str] = None
    EDI_Edificio: int # FK

class NivelCreate(NivelBase):
    pass

class NivelResponse(NivelBase):
    NIV_Nivel: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# 7. AREA (Oficina Final)
# =======================
class AreaBase(BaseModel):
    ARE_Nombre: str = Field(..., min_length=2, max_length=150)
    ARE_Tipo_Acceso: str = "General"
    ARE_Descripcion: Optional[str] = None
    NIV_Nivel: int # FK

class AreaCreate(AreaBase):
    pass

class AreaResponse(AreaBase):
    ARE_Area: int
    model_config = ConfigDict(from_attributes=True)