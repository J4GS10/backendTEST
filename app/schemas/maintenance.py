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

class MantenimientoResponse(MantenimientoBase):
    MAN_Mantenimiento: uuid.UUID
    MAN_Fecha_Ingreso: datetime
    MAN_Fecha_Cierre: Optional[datetime] = None
    
    # Objetos anidados para mostrar nombres en tabla
    tipo_mantenimiento: Optional[TipoMantenimientoResponse] = None
    detalles: List[DetalleResponse] = []
    
    # Resumen del activo
    activo: Optional[object] = None 

    model_config = ConfigDict(from_attributes=True)