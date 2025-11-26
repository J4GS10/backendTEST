from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
import uuid

# =======================
# TIPOS DE MOVIMIENTO
# =======================
class TipoMovimientoBase(BaseModel):
    TMO_Nombre: str = Field(..., min_length=3, max_length=50)

class TipoMovimientoCreate(TipoMovimientoBase):
    pass

class TipoMovimientoResponse(TipoMovimientoBase):
    TMO_Tipo_Movimiento: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# MOVIMIENTOS (ASIGNACIONES)
# =======================
class MovimientoBase(BaseModel):
    ACT_Activo: uuid.UUID
    PER_Persona: uuid.UUID
    ARE_Area: int
    TMO_Tipo_Movimiento: int # 1=Asignacion, 2=Prestamo, etc.
    MOV_Observacion: Optional[str] = None

class MovimientoCreate(MovimientoBase):
    """
    Solo pedimos los datos básicos. 
    La fecha de inicio la pone el sistema (NOW).
    La fecha fin se queda en NULL (Vigente).
    """
    pass

class MovimientoResponse(MovimientoBase):
    MOV_Movimiento: uuid.UUID
    MOV_Fecha_Asignacion: datetime
    MOV_Fecha_Devolucion: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)