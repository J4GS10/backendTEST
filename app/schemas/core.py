from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict, model_validator
from datetime import date
import uuid
from decimal import Decimal


# ── Schemas anidados para ActivoDetailResponse ────────────────────────────────

class MarcaAnidada(BaseModel):
    MAR_Marca: int
    MAR_Nombre: str
    model_config = ConfigDict(from_attributes=True)


class ModeloAnidado(BaseModel):
    MOD_Modelo: int
    MOD_Nombre: str
    marca: Optional[MarcaAnidada] = None
    model_config = ConfigDict(from_attributes=True)


class TipoActivoAnidado(BaseModel):
    TAC_Tipo_Activo: int
    TAC_Nombre: str
    model_config = ConfigDict(from_attributes=True)


class EstadoAnidado(BaseModel):
    EOP_Estado_Operativo: int
    EOP_Nombre: str
    model_config = ConfigDict(from_attributes=True)

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


# Respuesta enriquecida: incluye nombre y unidad del tipo (para la UI).
class EspecificacionDetalle(BaseModel):
    ESP_Especificacion: int
    TES_Tipo_Especificacion: int
    TES_Nombre: str
    TES_Unidad_Medida: Optional[str] = None
    ESP_Valor: str


class EspecificacionValorUpdate(BaseModel):
    ESP_Valor: str = Field(..., min_length=1, max_length=255)

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
    # Sede a la que pertenece (alcance de datos). Si el usuario tiene una sola
    # sede y no la indica, se usa esa.
    SED_Sede: Optional[int] = None

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
    SED_Sede: Optional[int] = None

class ActivoResponse(ActivoBase):
    ACT_Activo: uuid.UUID
    # Incluimos las specs en la respuesta
    especificaciones: List[EspecificacionResponse] = []
    
    model_config = ConfigDict(from_attributes=True)

class ActivoDetailResponse(ActivoResponse):
    """Vista enriquecida: incluye objetos anidados de modelo, tipo y estado
    para que el frontend no necesite lookups secundarios."""
    modelo: Optional[ModeloAnidado] = None
    tipo_activo: Optional[TipoActivoAnidado] = None
    estado_operativo: Optional[EstadoAnidado] = None

class EtiquetasActivosRequest(BaseModel):
    activos_ids: Optional[List[uuid.UUID]] = None
    codigos: Optional[List[str]] = None

    @model_validator(mode="after")
    def _validate_batch(self):
        total = len(self.activos_ids or []) + len(self.codigos or [])
        if total == 0:
            raise ValueError("LABEL_ASSETS_REQUIRED")
        if total > 200:
            raise ValueError("TOO_MANY_LABELS_REQUESTED")
        return self


class ActivoFilter(BaseModel):
    # max_length=64 acota el coste de la búsqueda LIKE; los metacaracteres
    # `%` y `_` se escapan en el repository antes de pasarse a ilike().
    q: Optional[str] = Field(
        None, max_length=64,
        description="Búsqueda combinada en código, serie, hostname (max 64 chars)",
    )
    modelo_id: Optional[int] = None
    tipo_activo_id: Optional[int] = None
    estado_operativo_id: Optional[int] = None
    sede_id: Optional[int] = None
    fecha_compra_start: Optional[date] = None
    fecha_compra_end: Optional[date] = None
    page: int = Field(1, ge=1, description="Página 1-indexed")
    per_page: int = Field(20, ge=1, le=200, description="Tamaño de página, máximo 200")
