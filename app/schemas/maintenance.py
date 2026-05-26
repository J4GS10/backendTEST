from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from decimal import Decimal
import uuid

# --- TIPO MANTENIMIENTO ---
class TipoMantenimientoBase(BaseModel):
    TMA_Nombre: str = Field(..., min_length=3, max_length=50)

class TipoMantenimientoCreate(TipoMantenimientoBase):
    pass

class TipoMantenimientoUpdate(BaseModel):
    TMA_Nombre: Optional[str] = Field(None, min_length=3, max_length=50)

class TipoMantenimientoResponse(TipoMantenimientoBase):
    TMA_Tipo_Mantenimiento: int
    model_config = ConfigDict(from_attributes=True)

# --- DETALLE (ITEMS) ---
class DetalleMantenimientoBase(BaseModel):
    DMA_Accion_Realizada: str = Field(..., min_length=5, max_length=255)
    DMA_Costo_Item: Decimal = Field(default=0, ge=0)

class DetalleCreate(DetalleMantenimientoBase):
    pass

class DetalleResponse(DetalleMantenimientoBase):
    DMA_Detalle_Mant: int
    model_config = ConfigDict(from_attributes=True)

# --- MANTENIMIENTO (CABECERA) ---
class MantenimientoBase(BaseModel):
    ACT_Activo: uuid.UUID
    PER_Persona_Solicita: uuid.UUID
    TMA_Tipo_Mantenimiento: int
    MAN_Descripcion_Falla: str
    MAN_Costo_Total: Decimal = Field(default=0, ge=0)

class MantenimientoCreate(MantenimientoBase):
    # Lista opcional de acciones realizadas
    detalles: List[DetalleCreate] = []

class MantenimientoCierre(BaseModel):
    MAN_Costo_Total: Decimal = Field(..., ge=0)
    MAN_Fecha_Cierre: Optional[datetime] = None


class ActivoMantSummary(BaseModel):
    ACT_Activo: uuid.UUID
    ACT_Codigo_Interno: str
    ACT_Hostname: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class PersonaMantSummary(BaseModel):
    PER_Persona: uuid.UUID
    PER_Primer_Nombre: str
    PER_Primer_Apellido: str
    PER_Email_Corporativo: str
    model_config = ConfigDict(from_attributes=True)


class MantenimientoResponse(MantenimientoBase):
    MAN_Mantenimiento: uuid.UUID
    MAN_Fecha_Ingreso: datetime
    MAN_Fecha_Cierre: Optional[datetime] = None

    # Relaciones cargadas
    tipo_mantenimiento: Optional[TipoMantenimientoResponse] = None
    detalles: List[DetalleResponse] = []
    activo: Optional[ActivoMantSummary] = None
    persona_solicita: Optional[PersonaMantSummary] = None

    model_config = ConfigDict(from_attributes=True)