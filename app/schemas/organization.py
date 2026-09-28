from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, model_validator

from app.core.roles import ROLE_PATTERN
from app.schemas.common import CorporateEmail
from datetime import datetime
import uuid

# =======================
# 1. DEPARTAMENTO
# =======================
class DepartamentoBase(BaseModel):
    DEP_Nombre: str = Field(..., min_length=3, max_length=100)
    DEP_Codigo_Costos: Optional[str] = Field(None, max_length=50)
    DEP_Descripcion: Optional[str] = Field(None, max_length=255)

class DepartamentoCreate(DepartamentoBase):
    pass

class DepartamentoUpdate(BaseModel):
    DEP_Nombre: Optional[str] = Field(None, min_length=3, max_length=100)
    DEP_Codigo_Costos: Optional[str] = Field(None, max_length=50)
    DEP_Descripcion: Optional[str] = Field(None, max_length=255)
    DEP_Activo: Optional[bool] = None

class DepartamentoResponse(DepartamentoBase):
    DEP_Departamento: int
    DEP_Activo: bool
    model_config = ConfigDict(from_attributes=True)

# =======================
# 2. CARGO
# =======================
class CargoBase(BaseModel):
    CAR_Nombre: str = Field(..., min_length=3, max_length=100)
    CAR_Es_Jefatura: bool = False
    CAR_Descripcion: Optional[str] = Field(None, max_length=255)

class CargoCreate(CargoBase):
    pass

class CargoUpdate(BaseModel):
    CAR_Nombre: Optional[str] = Field(None, min_length=3, max_length=100)
    CAR_Es_Jefatura: Optional[bool] = None
    CAR_Descripcion: Optional[str] = Field(None, max_length=255)

class CargoResponse(CargoBase):
    CAR_Cargo: int
    model_config = ConfigDict(from_attributes=True)

# =======================
# 3. PERSONA
# =======================
class PersonaBase(BaseModel):
    PER_Primer_Nombre: str = Field(..., min_length=2, max_length=50)
    PER_Segundo_Nombre: Optional[str] = Field(None, max_length=50)
    PER_Primer_Apellido: str = Field(..., min_length=2, max_length=50)
    PER_Segundo_Apellido: Optional[str] = Field(None, max_length=50)
    PER_Email_Corporativo: CorporateEmail
    PER_Telefono: Optional[str] = Field(None, max_length=20)
    
    # FKs
    DEP_Departamento: int
    CAR_Cargo: int
    PER_Jefe: Optional[uuid.UUID] = None
    # Sede donde trabaja (alcance de datos). Obligatoria para usuarios con
    # alcance por sede; si tienen una sola, se usa esa.
    SED_Sede: Optional[int] = None

class PersonaCreate(PersonaBase):
    pass

class PersonaUpdate(BaseModel):
    PER_Primer_Nombre: Optional[str] = Field(None, min_length=2, max_length=50)
    PER_Segundo_Nombre: Optional[str] = Field(None, max_length=50)
    PER_Primer_Apellido: Optional[str] = Field(None, min_length=2, max_length=50)
    PER_Segundo_Apellido: Optional[str] = Field(None, max_length=50)
    PER_Email_Corporativo: Optional[CorporateEmail] = None
    PER_Telefono: Optional[str] = Field(None, max_length=20)
    DEP_Departamento: Optional[int] = None
    CAR_Cargo: Optional[int] = None
    PER_Jefe: Optional[uuid.UUID] = None
    SED_Sede: Optional[int] = None
    PER_Estado: Optional[bool] = None

class PersonaResponse(PersonaBase):
    PER_Persona: uuid.UUID
    PER_Email_Corporativo: str
    PER_Estado: bool
    PER_AD_GUID: Optional[str] = None
    PER_AD_Sincronizado_En: Optional[datetime] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# =======================
# 4. USUARIO
# =======================
class UsuarioCreate(BaseModel):
    USU_Username: str = Field(..., min_length=4, max_length=50)
    # max_length acota el coste de hashing (bcrypt) → evita DoS por password gigante.
    USU_Password: Optional[str] = Field(None, min_length=8, max_length=128)
    USU_Rol: str = Field(..., pattern=ROLE_PATTERN)
    USU_SSO_Habilitado: bool = False
    USU_SSO_Provider: Optional[str] = Field(None, pattern="^(microsoft|google)$")
    PER_Persona: uuid.UUID
    # Alcance de datos: global (solo lo otorga un SUPER_ADMIN) o lista de sedes.
    USU_Alcance_Global: bool = False
    sedes: list[int] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _auth_method_required(self):
        if not self.USU_Password and not self.USU_SSO_Habilitado:
            raise ValueError("AUTH_METHOD_REQUIRED")
        if self.USU_SSO_Provider and not self.USU_SSO_Habilitado:
            raise ValueError("SSO_PROVIDER_REQUIRES_SSO_ENABLED")
        return self

class UsuarioUpdate(BaseModel):
    USU_Password: Optional[str] = Field(None, min_length=8, max_length=128)
    USU_Rol: Optional[str] = Field(None, pattern=ROLE_PATTERN)
    USU_Estado: Optional[bool] = None
    USU_SSO_Habilitado: Optional[bool] = None
    USU_SSO_Provider: Optional[str] = Field(None, pattern="^(microsoft|google)$")
    USU_Alcance_Global: Optional[bool] = None
    sedes: Optional[list[int]] = Field(None, max_length=200)

class SedeRef(BaseModel):
    SED_Sede: int
    SED_Nombre: str
    model_config = ConfigDict(from_attributes=True)

class UsuarioResponse(BaseModel):
    USU_Usuario: uuid.UUID
    USU_Username: str
    USU_Rol: str
    USU_Estado: bool
    USU_SSO_Habilitado: bool = False
    USU_SSO_Provider: Optional[str] = None
    USU_2FA_Habilitado: bool = False
    USU_2FA_Metodo: Optional[str] = None
    USU_Ultimo_Login: Optional[datetime]
    # Estado de seguridad (panel de identidades y accesos)
    USU_Debe_Cambiar_Password: bool = False
    USU_Bloqueado_Hasta: Optional[datetime] = None
    USU_Intentos_Fallidos: int = 0
    USU_Password_Cambiada_En: Optional[datetime] = None
    mfa_requerido: bool = False
    # Alcance de datos
    USU_Alcance_Global: bool = False
    alcance_global_efectivo: bool = False
    sedes: list[SedeRef] = []
    USU_Creado_En: Optional[datetime] = None
    # Usamos PersonaResponse para exponer PER_Persona, PER_Estado, created_at
    # (el frontend los necesita para mostrar nombre completo, estado y ordenar).
    persona: Optional[PersonaResponse] = None

    model_config = ConfigDict(from_attributes=True)
