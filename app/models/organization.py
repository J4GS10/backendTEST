import uuid
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base

# ==========================================
# 1. ENTIDAD: DEPARTAMENTO
# ==========================================
class Departamento(Base):
    __tablename__ = "INV_DEPARTAMENTO"

    DEP_Departamento = Column(Integer, primary_key=True, index=True, autoincrement=True)
    
    DEP_Nombre = Column(String(100), nullable=False, unique=True)
    DEP_Codigo_Costos = Column(String(50), nullable=True)
    DEP_Descripcion = Column(String(255), nullable=True)
    DEP_Activo = Column(Boolean, default=True)

    # Relaciones
    personas = relationship("Persona", back_populates="departamento")


# ==========================================
# 2. ENTIDAD: CARGO
# ==========================================
class Cargo(Base):
    __tablename__ = "INV_CARGO"

    CAR_Cargo = Column(Integer, primary_key=True, index=True, autoincrement=True)
    
    CAR_Nombre = Column(String(100), nullable=False, unique=True)
    CAR_Es_Jefatura = Column(Boolean, default=False)
    CAR_Descripcion = Column(String(255), nullable=True)

    personas = relationship("Persona", back_populates="cargo")


# ==========================================
# 3. ENTIDAD: PERSONA
# ==========================================
class Persona(Base):
    __tablename__ = "INV_PERSONA"

    PER_Persona = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    PER_Primer_Nombre = Column(String(50), nullable=False)
    PER_Segundo_Nombre = Column(String(50), nullable=True)
    PER_Primer_Apellido = Column(String(50), nullable=False)
    PER_Segundo_Apellido = Column(String(50), nullable=True)
    
    PER_Email_Corporativo = Column(String(150), unique=True, nullable=False, index=True)
    PER_Telefono = Column(String(20), nullable=True)
    PER_Estado = Column(Boolean, default=True)
    
    # FKs
    DEP_Departamento = Column(Integer, ForeignKey("INV_DEPARTAMENTO.DEP_Departamento"), nullable=False)
    CAR_Cargo = Column(Integer, ForeignKey("INV_CARGO.CAR_Cargo"), nullable=False)

    # Auditoría
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relaciones
    departamento = relationship("Departamento", back_populates="personas")
    cargo = relationship("Cargo", back_populates="personas")
    
    # Relación 1 a 1 con Usuario
    usuario = relationship("Usuario", uselist=False, back_populates="persona")


# ==========================================
# 4. ENTIDAD: USUARIO (LA QUE FALTABA)
# ==========================================
class Usuario(Base):
    __tablename__ = "INV_USUARIO"

    # PK: UUID
    USU_Usuario = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    USU_Username = Column(String(50), unique=True, nullable=False, index=True)
    USU_Password_Hash = Column(String(255), nullable=False)
    USU_Salt = Column(String(255), nullable=False) # Para mayor seguridad
    
    USU_Ultimo_Login = Column(DateTime, nullable=True)
    USU_Rol = Column(String(20), nullable=False) # SUPER_ADMIN, ADMIN_TI, TECNICO
    USU_Estado = Column(Boolean, default=True) # Kill Switch

    # FK 1:1 con Persona
    PER_Persona = Column(UUID(as_uuid=True), ForeignKey("INV_PERSONA.PER_Persona"), unique=True, nullable=False)

    # Relaciones
    persona = relationship("Persona", back_populates="usuario")