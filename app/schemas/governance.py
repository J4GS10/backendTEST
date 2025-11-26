from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

class ConfigUpdate(BaseModel):
    SYS_Nombre_Empresa: Optional[str] = Field(None, min_length=2, max_length=100)
    SYS_Logo_URL: Optional[str] = None
    SYS_Color_Primario: Optional[str] = Field(None, pattern="^#[0-9a-fA-F]{6}$")
    SYS_Color_Secundario: Optional[str] = Field(None, pattern="^#[0-9a-fA-F]{6}$")
    SYS_Idioma_Defecto: Optional[str] = Field(None, max_length=2)

class ConfigResponse(ConfigUpdate):
    SYS_Configuracion: int 
    model_config = ConfigDict(from_attributes=True)