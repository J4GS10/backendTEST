from typing import Optional
from pydantic import BaseModel, Field, EmailStr, ConfigDict
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
    CAR_Descripcion: Optional[str] = None

class CargoCreate(CargoBase):
    pass

class CargoUpdate(BaseModel):
    CAR_Nombre: Optional[str] = Field(None, min_length=3, max_length=100)
    CAR_Es_Jefatura: Optional[bool] = None
    CAR_Descripcion: Optional[str] = None

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
    PER_Email_Corporativo: EmailStr
    PER_Telefono: Optional[str] = Field(None, max_length=20)
    
    # FKs
    DEP_Departamento: int
    CAR_Cargo: int

class PersonaCreate(PersonaBase):
    pass

class PersonaUpdate(BaseModel):
    PER_Primer_Nombre: Optional[str] = Field(None, min_length=2, max_length=50)
    PER_Segundo_Nombre: Optional[str] = Field(None, max_length=50)
    PER_Primer_Apellido: Optional[str] = Field(None, min_length=2, max_length=50)
    PER_Segundo_Apellido: Optional[str] = Field(None, max_length=50)
    PER_Email_Corporativo: Optional[EmailStr] = None
    PER_Telefono: Optional[str] = Field(None, max_length=20)
    DEP_Departamento: Optional[int] = None
    CAR_Cargo: Optional[int] = None
    PER_Estado: Optional[bool] = None

class PersonaResponse(PersonaBase):
    PER_Persona: uuid.UUID
    PER_Estado: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# =======================
# 4. USUARIO
# =======================
class UsuarioCreate(BaseModel):
    USU_Username: str = Field(..., min_length=4, max_length=50)
    USU_Password: str = Field(..., min_length=8)
    USU_Rol: str = Field(..., pattern="^(SUPER_ADMIN|ADMIN_TI|TECNICO|CONSULTA)$")
    PER_Persona: uuid.UUID 

class UsuarioUpdate(BaseModel):
    USU_Password: Optional[str] = Field(None, min_length=8)
    USU_Rol: Optional[str] = Field(None, pattern="^(SUPER_ADMIN|ADMIN_TI|TECNICO|CONSULTA)$")
    USU_Estado: Optional[bool] = None

class UsuarioResponse(BaseModel):
    USU_Usuario: uuid.UUID
    USU_Username: str
    USU_Rol: str
    USU_Estado: bool
    USU_Ultimo_Login: Optional[datetime]
    # Usamos PersonaResponse para exponer PER_Persona, PER_Estado, created_at
    # (el frontend los necesita para mostrar nombre completo, estado y ordenar).
    persona: Optional[PersonaResponse] = None

    model_config = ConfigDict(from_attributes=True)