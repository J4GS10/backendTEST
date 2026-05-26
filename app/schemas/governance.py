from datetime import datetime
from typing import Any, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ConfigUpdate(BaseModel):
    SYS_Nombre_Empresa: Optional[str] = Field(None, min_length=2, max_length=100)
    SYS_Logo_URL: Optional[str] = Field(None, max_length=500)
    SYS_Color_Primario: Optional[str] = Field(None, pattern="^#([0-9a-fA-F]{3}){1,2}$")
    SYS_Color_Secundario: Optional[str] = Field(None, pattern="^#([0-9a-fA-F]{3}){1,2}$")
    SYS_Idioma_Defecto: Optional[str] = Field(None, max_length=2)


class ConfigResponse(ConfigUpdate):
    SYS_Configuracion: int
    model_config = ConfigDict(from_attributes=True)


class AuditoriaResponse(BaseModel):
    AUD_Auditoria: uuid.UUID
    AUD_Fecha_Hora: datetime
    AUD_Accion: str
    AUD_Entidad_Afectada: str
    AUD_Snapshot_JSON: Optional[Any] = None
    AUD_IP_Origen: Optional[str] = None
    AUD_User_Agent: Optional[str] = None
    USU_Usuario: Optional[uuid.UUID] = None
    model_config = ConfigDict(from_attributes=True)


class AuditoriaList(BaseModel):
    total: int
    items: List[AuditoriaResponse]
