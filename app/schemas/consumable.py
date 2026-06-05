from typing import Optional
from datetime import datetime
import uuid

from pydantic import BaseModel, Field, ConfigDict


# =======================
# CONSUMIBLE
# =======================
class ConsumibleBase(BaseModel):
    CON_Nombre: str = Field(..., min_length=2, max_length=100)
    CON_Descripcion: Optional[str] = Field(None, max_length=255)
    CON_Categoria: Optional[str] = Field(None, max_length=50)
    CON_Unidad: str = Field("unidad", min_length=1, max_length=20)
    CON_Stock_Minimo: int = Field(0, ge=0)


class ConsumibleCreate(ConsumibleBase):
    # Stock inicial opcional al dar de alta el consumible.
    CON_Stock_Actual: int = Field(0, ge=0)


class ConsumibleUpdate(BaseModel):
    CON_Nombre: Optional[str] = Field(None, min_length=2, max_length=100)
    CON_Descripcion: Optional[str] = Field(None, max_length=255)
    CON_Categoria: Optional[str] = Field(None, max_length=50)
    CON_Unidad: Optional[str] = Field(None, min_length=1, max_length=20)
    CON_Stock_Minimo: Optional[int] = Field(None, ge=0)
    CON_Activo: Optional[bool] = None


class ConsumibleResponse(ConsumibleBase):
    CON_Consumible: int
    CON_Stock_Actual: int
    CON_Activo: bool
    # Calculado: stock actual <= mínimo (y mínimo > 0).
    bajo_stock: bool = False
    model_config = ConfigDict(from_attributes=True)


# =======================
# MOVIMIENTO DE STOCK
# =======================
class StockMovimientoCreate(BaseModel):
    """Entrada o salida de stock."""
    MOC_Cantidad: int = Field(..., gt=0)
    MOC_Motivo: Optional[str] = Field(None, max_length=255)
    PER_Persona: Optional[uuid.UUID] = None


class MovimientoConsumibleResponse(BaseModel):
    MOC_Movimiento: int
    MOC_Tipo: str
    MOC_Cantidad: int
    MOC_Stock_Resultante: int
    MOC_Motivo: Optional[str] = None
    MOC_Fecha: datetime
    CON_Consumible: int
    PER_Persona: Optional[uuid.UUID] = None
    USU_Usuario: Optional[uuid.UUID] = None
    model_config = ConfigDict(from_attributes=True)
