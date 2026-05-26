from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from datetime import date
import uuid
from decimal import Decimal

# =======================
# ESPECIFICACIONES (EAV)
# =======================
class EspecificacionBase(BaseModel):
    TES_Tipo_Especificacion: int 
    ESP_Valor: str = Field(..., min_length=1, max_length=255)

class EspecificacionCreate(EspecificacionBase):
    pass

class EspecificacionResponse(EspecificacionBase):
    ESP_Especificacion: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# ACTIVO (CORE)
# =======================
class ActivoBase(BaseModel):
    ACT_Codigo_Interno: Optional[str] = Field(None, min_length=3, max_length=50) # Opcional en entrada por secuencia
    ACT_Serie_Fabricante: str = Field(..., min_length=3, max_length=100)
    ACT_Hostname: Optional[str] = Field(None, max_length=100)
    
    ACT_Fecha_Compra: date
    ACT_Fin_Garantia: Optional[date] = None
    ACT_Costo: Optional[Decimal] = Field(
        None, 
        ge=0, 
        max_digits=12, 
        decimal_places=2,
        json_schema_extra={"example": 1500.50} 
    )

    # FKs
    MOD_Modelo: int
    TAC_Tipo_Activo: int
    EOP_Estado_Operativo: int
    ACT_Activo_Padre: Optional[uuid.UUID] = None

class ActivoCreate(ActivoBase):
    # Permitimos crear especificaciones junto con el activo (Nested Write)
    especificaciones: Optional[List[EspecificacionCreate]] = []

class ActivoUpdate(BaseModel):
    ACT_Codigo_Interno: Optional[str] = Field(None, min_length=3, max_length=50)
    ACT_Serie_Fabricante: Optional[str] = Field(None, min_length=3, max_length=100)
    ACT_Hostname: Optional[str] = Field(None, max_length=100)
    ACT_Costo: Optional[Decimal] = Field(None, ge=0)
    
    MOD_Modelo: Optional[int] = None
    TAC_Tipo_Activo: Optional[int] = None
    EOP_Estado_Operativo: Optional[int] = None

class ActivoResponse(ActivoBase):
    ACT_Activo: uuid.UUID
    # Incluimos las specs en la respuesta
    especificaciones: List[EspecificacionResponse] = []
    
    model_config = ConfigDict(from_attributes=True)

class ActivoDetailResponse(ActivoResponse):
    # Incluye relaciones adicionales para la vista de detalle
    pass  # Por ahora igual, pero preparado para expansión (ej. historial)

class ActivoFilter(BaseModel):
    q: Optional[str] = Field(None, description="Búsqueda combinada en código, serie, hostname")
    modelo_id: Optional[int] = None
    tipo_activo_id: Optional[int] = None
    estado_operativo_id: Optional[int] = None
    fecha_compra_start: Optional[date] = None
    fecha_compra_end: Optional[date] = None
    page: int = Field(1, ge=1, description="Página 1-indexed")
    per_page: int = Field(20, ge=1, le=200, description="Tamaño de página, máximo 200")
