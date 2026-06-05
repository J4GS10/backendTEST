from typing import Optional
from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict


class AdjuntoResponse(BaseModel):
    ADJ_Adjunto: uuid.UUID
    ADJ_Nombre_Original: str
    ADJ_Tipo_MIME: Optional[str] = None
    ADJ_Tamano_Bytes: int
    ADJ_Categoria: str
    ADJ_Descripcion: Optional[str] = None
    ADJ_Fecha_Subida: datetime
    ACT_Activo: Optional[uuid.UUID] = None
    OCO_Orden: Optional[int] = None
    USU_Usuario: Optional[uuid.UUID] = None
    model_config = ConfigDict(from_attributes=True)
