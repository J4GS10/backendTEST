from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from datetime import date
import uuid

# --- TIPO LICENCIA ---
class TipoLicenciaBase(BaseModel):
    TLI_Nombre: str = Field(..., min_length=2, max_length=50)
    TLI_Descripcion: Optional[str] = None

class TipoLicenciaCreate(TipoLicenciaBase):
    pass

class TipoLicenciaResponse(TipoLicenciaBase):
    TLI_Tipo_Licencia: int
    model_config = ConfigDict(from_attributes=True)

# --- SOFTWARE ---
class SoftwareBase(BaseModel):
    SOF_Nombre: str = Field(..., min_length=2, max_length=100)
    SOF_Version: Optional[str] = Field(None, max_length=50)
    SOF_Fabricante: str = Field(..., min_length=2, max_length=100)

class SoftwareCreate(SoftwareBase):
    pass

class SoftwareResponse(SoftwareBase):
    SOF_Software: int
    model_config = ConfigDict(from_attributes=True)

# --- LICENCIA (Inventario) ---
class LicenciaBase(BaseModel):
    LIC_Clave_Activacion: Optional[str] = Field(None, description="Serial Key")
    LIC_Fecha_Vencimiento: Optional[date] = None
    LIC_Cantidad_Total: int = Field(..., gt=0, description="Total de asientos comprados")
    
    # FKs
    SOF_Software: int
    TLI_Tipo_Licencia: int

class LicenciaCreate(LicenciaBase):
    pass

class LicenciaResponse(LicenciaBase):
    LIC_Licencia: int
    LIC_Cantidad_Usada: int # Campo calculado/gestionado por el sistema
    model_config = ConfigDict(from_attributes=True)

# --- INSTALACIÓN (Asignación) ---
class InstalacionBase(BaseModel):
    ACT_Activo: uuid.UUID
    LIC_Licencia: int
    INS_Fecha_Instalacion: date = Field(default_factory=date.today)

class InstalacionCreate(InstalacionBase):
    pass

class InstalacionResponse(InstalacionBase):
    INS_Instalacion: int
    INS_Estado: bool
    model_config = ConfigDict(from_attributes=True)