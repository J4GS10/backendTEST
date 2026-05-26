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

class TipoMovimientoUpdate(BaseModel):
    TMO_Nombre: Optional[str] = Field(None, min_length=3, max_length=50)

class TipoMovimientoResponse(TipoMovimientoBase):
    TMO_Tipo_Movimiento: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# SCHEMAS ANIDADOS (Para mostrar nombres, no solo IDs)
# =======================
class ActivoSummary(BaseModel):
    ACT_Codigo_Interno: str
    ACT_Hostname: Optional[str] = None

class PersonaSummary(BaseModel):
    PER_Primer_Nombre: str
    PER_Primer_Apellido: str
    PER_Email_Corporativo: str

class AreaSummary(BaseModel):
    ARE_Nombre: str

# =======================
# MOVIMIENTOS (ASIGNACIONES)
# =======================
class MovimientoBase(BaseModel):
    ACT_Activo: uuid.UUID
    PER_Persona: uuid.UUID
    ARE_Area: int
    TMO_Tipo_Movimiento: int 
    MOV_Observacion: Optional[str] = None

class MovimientoCreate(MovimientoBase):
    pass

class MovimientoResponse(MovimientoBase):
    MOV_Movimiento: uuid.UUID
    MOV_Fecha_Asignacion: datetime
    MOV_Fecha_Devolucion: Optional[datetime] = None
    
    # --- AQUÍ ESTÁ LA MAGIA QUE FALTABA ---
    # Estos campos coinciden con los nombres de las relaciones en el Modelo SQLAlchemy
    activo: Optional[ActivoSummary] = None
    persona: Optional[PersonaSummary] = None
    tipo_movimiento: Optional[TipoMovimientoResponse] = None
    area: Optional[AreaSummary] = None
    
    model_config = ConfigDict(from_attributes=True)

# =======================
# DEVOLUCIÓN
# =======================
class DevolucionCreate(BaseModel):
    ACT_Activo: uuid.UUID

# =======================
# TRANSFERENCIA
# =======================
class TransferenciaCreate(BaseModel):
    ACT_Activo: uuid.UUID
    PER_Persona_Destino: uuid.UUID
    ARE_Area_Destino: int
    MOV_Observacion: Optional[str] = None

# Request para descarga por lote
class ActaLoteRequest(BaseModel):
    movimientos_ids: List[uuid.UUID]