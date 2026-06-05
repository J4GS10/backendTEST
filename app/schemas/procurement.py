from typing import List, Optional
from datetime import date, datetime
from decimal import Decimal
import uuid

from pydantic import BaseModel, Field, ConfigDict, EmailStr


# =======================
# PROVEEDOR
# =======================
class ProveedorBase(BaseModel):
    PRV_Nombre: str = Field(..., min_length=2, max_length=150)
    PRV_Identificacion_Fiscal: Optional[str] = Field(None, max_length=50)
    PRV_Contacto: Optional[str] = Field(None, max_length=100)
    PRV_Email: Optional[EmailStr] = None
    PRV_Telefono: Optional[str] = Field(None, max_length=30)
    PRV_Direccion: Optional[str] = Field(None, max_length=255)


class ProveedorCreate(ProveedorBase):
    pass


class ProveedorUpdate(BaseModel):
    PRV_Nombre: Optional[str] = Field(None, min_length=2, max_length=150)
    PRV_Identificacion_Fiscal: Optional[str] = Field(None, max_length=50)
    PRV_Contacto: Optional[str] = Field(None, max_length=100)
    PRV_Email: Optional[EmailStr] = None
    PRV_Telefono: Optional[str] = Field(None, max_length=30)
    PRV_Direccion: Optional[str] = Field(None, max_length=255)
    PRV_Activo: Optional[bool] = None


class ProveedorResponse(ProveedorBase):
    PRV_Proveedor: int
    PRV_Activo: bool
    model_config = ConfigDict(from_attributes=True)


# =======================
# LÍNEA DE ORDEN
# =======================
class LineaCreate(BaseModel):
    OCL_Descripcion: str = Field(..., min_length=1, max_length=255)
    OCL_Cantidad: int = Field(1, gt=0)
    OCL_Precio_Unitario: Decimal = Field(0, ge=0)
    ACT_Activo: Optional[uuid.UUID] = None
    CON_Consumible: Optional[int] = None


class LineaResponse(BaseModel):
    OCL_Linea: int
    OCL_Descripcion: str
    OCL_Cantidad: int
    OCL_Precio_Unitario: Decimal
    OCL_Subtotal: Decimal
    ACT_Activo: Optional[uuid.UUID] = None
    CON_Consumible: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


# =======================
# ORDEN DE COMPRA
# =======================
class OrdenCreate(BaseModel):
    OCO_Numero: str = Field(..., min_length=1, max_length=50)
    OCO_Fecha: date
    OCO_Moneda: str = Field("USD", min_length=3, max_length=3)
    OCO_Notas: Optional[str] = Field(None, max_length=500)
    PRV_Proveedor: int
    lineas: List[LineaCreate] = Field(default_factory=list)


class OrdenEstadoUpdate(BaseModel):
    OCO_Estado: str = Field(..., pattern="^(BORRADOR|RECIBIDA|CANCELADA)$")


# =======================
# RECEPCIÓN DE ORDEN (lazo cerrado: stock de consumibles + alta de activos)
# =======================
class RecepcionConsumible(BaseModel):
    """Una línea que reabastece un consumible: suma `cantidad` a su stock."""
    OCL_Linea: int
    CON_Consumible: int
    cantidad: int = Field(..., gt=0)


class RecepcionActivo(BaseModel):
    """Una línea que se convierte en un activo nuevo (alta + enlace a la orden)."""
    OCL_Linea: int
    ACT_Codigo_Interno: Optional[str] = Field(None, min_length=3, max_length=50)
    ACT_Serie_Fabricante: str = Field(..., min_length=3, max_length=100)
    ACT_Hostname: Optional[str] = Field(None, max_length=100)
    MOD_Modelo: int
    TAC_Tipo_Activo: int
    ACT_Fecha_Compra: date
    ACT_Fin_Garantia: Optional[date] = None
    ACT_Costo: Optional[Decimal] = Field(None, ge=0)


class RecepcionOrden(BaseModel):
    consumibles: List[RecepcionConsumible] = Field(default_factory=list)
    activos: List[RecepcionActivo] = Field(default_factory=list)


class RecepcionResultado(BaseModel):
    OCO_Orden: int
    OCO_Estado: str
    consumibles_reabastecidos: int
    activos_creados: int
    activos_codigos: List[str] = Field(default_factory=list)


class _ProveedorSummary(BaseModel):
    PRV_Proveedor: int
    PRV_Nombre: str
    model_config = ConfigDict(from_attributes=True)


class OrdenResponse(BaseModel):
    OCO_Orden: int
    OCO_Numero: str
    OCO_Fecha: date
    OCO_Estado: str
    OCO_Moneda: str
    OCO_Total: Decimal
    OCO_Notas: Optional[str] = None
    PRV_Proveedor: int
    proveedor: Optional[_ProveedorSummary] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class OrdenDetalleResponse(OrdenResponse):
    lineas: List[LineaResponse] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


# =======================
# GARANTÍAS
# =======================
class GarantiaItem(BaseModel):
    ACT_Activo: uuid.UUID
    ACT_Codigo_Interno: str
    ACT_Serie_Fabricante: str
    ACT_Fecha_Compra: date
    ACT_Fin_Garantia: Optional[date] = None
    dias_restantes: Optional[int] = None
    estado_garantia: str  # vigente | por_vencer | vencida | sin_garantia
    proveedor: Optional[str] = None
