from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from datetime import date
import uuid

# --- TIPO LICENCIA ---
class TipoLicenciaBase(BaseModel):
    TLI_Nombre: str = Field(..., min_length=2, max_length=50)
    TLI_Descripcion: Optional[str] = Field(None, max_length=200)

class TipoLicenciaCreate(TipoLicenciaBase):
    pass

class TipoLicenciaUpdate(BaseModel):
    TLI_Nombre: Optional[str] = Field(None, min_length=2, max_length=50)
    TLI_Descripcion: Optional[str] = Field(None, max_length=200)

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

class SoftwareUpdate(BaseModel):
    SOF_Nombre: Optional[str] = Field(None, min_length=2, max_length=100)
    SOF_Version: Optional[str] = Field(None, max_length=50)
    SOF_Fabricante: Optional[str] = Field(None, min_length=2, max_length=100)

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
    # Cota SOLO en la entrada: el texto plano cifrado debe caber en la columna
    # (500, ciphertext). La base/respuesta quedan laxas para no romper la
    # lectura de claves legadas descifradas más largas.
    LIC_Clave_Activacion: Optional[str] = Field(None, max_length=255, description="Serial Key")

class LicenciaUpdate(BaseModel):
    LIC_Clave_Activacion: Optional[str] = Field(None, max_length=255)
    LIC_Fecha_Vencimiento: Optional[date] = None
    LIC_Cantidad_Total: Optional[int] = Field(None, gt=0)

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


class _SoftwareSummary(BaseModel):
    SOF_Software: int
    SOF_Nombre: str
    SOF_Version: Optional[str] = None
    SOF_Fabricante: str
    model_config = ConfigDict(from_attributes=True)


class _TipoLicenciaSummary(BaseModel):
    TLI_Tipo_Licencia: int
    TLI_Nombre: str
    model_config = ConfigDict(from_attributes=True)


class _LicenciaWithSoftware(BaseModel):
    LIC_Licencia: int
    LIC_Fecha_Vencimiento: Optional[date] = None
    LIC_Cantidad_Total: int
    LIC_Cantidad_Usada: int
    software: Optional[_SoftwareSummary] = None
    tipo_licencia: Optional[_TipoLicenciaSummary] = None
    model_config = ConfigDict(from_attributes=True)


class InstalacionDetalleResponse(InstalacionResponse):
    """Instalación con la licencia y software anidados (para mostrar en UI)."""
    licencia: Optional[_LicenciaWithSoftware] = None
    model_config = ConfigDict(from_attributes=True)