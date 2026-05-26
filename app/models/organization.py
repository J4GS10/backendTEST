import uuid
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, DateTime, func, Uuid,
    CheckConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


# ==========================================
# 1. DEPARTAMENTO
# ==========================================
class Departamento(Base):
    __tablename__ = "INV_DEPARTAMENTO"

    DEP_Departamento = Column(Integer, primary_key=True, index=True, autoincrement=True)
    DEP_Nombre = Column(String(100), nullable=False, unique=True)
    DEP_Codigo_Costos = Column(String(50), nullable=True)
    DEP_Descripcion = Column(String(255), nullable=True)
    DEP_Activo = Column(Boolean, default=True, nullable=False)

    personas = relationship("Persona", back_populates="departamento")


# ==========================================
# 2. CARGO
# ==========================================
class Cargo(Base):
    __tablename__ = "INV_CARGO"

    CAR_Cargo = Column(Integer, primary_key=True, index=True, autoincrement=True)
    CAR_Nombre = Column(String(100), nullable=False, unique=True)
    CAR_Es_Jefatura = Column(Boolean, default=False, nullable=False)
    CAR_Descripcion = Column(String(255), nullable=True)

    personas = relationship("Persona", back_populates="cargo")


# ==========================================
# 3. PERSONA
# ==========================================
class Persona(Base):
    __tablename__ = "INV_PERSONA"

    PER_Persona = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)

    PER_Primer_Nombre = Column(String(50), nullable=False)
    PER_Segundo_Nombre = Column(String(50), nullable=True)
    PER_Primer_Apellido = Column(String(50), nullable=False)
    PER_Segundo_Apellido = Column(String(50), nullable=True)

    PER_Email_Corporativo = Column(String(150), unique=True, nullable=False, index=True)
    PER_Telefono = Column(String(20), nullable=True)
    PER_Estado = Column(Boolean, default=True, nullable=False)

    DEP_Departamento = Column(
        Integer,
        ForeignKey("INV_DEPARTAMENTO.DEP_Departamento", ondelete="RESTRICT"),
        nullable=False,
    )
    CAR_Cargo = Column(
        Integer,
        ForeignKey("INV_CARGO.CAR_Cargo", ondelete="RESTRICT"),
        nullable=False,
    )

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())

    departamento = relationship("Departamento", back_populates="personas")
    cargo = relationship("Cargo", back_populates="personas")
    usuario = relationship("Usuario", uselist=False, back_populates="persona")

    __table_args__ = (
        # Validación básica de formato de email a nivel BD (defensa en profundidad).
        CheckConstraint(
            "\"PER_Email_Corporativo\" LIKE '%_@_%._%'",
            name="ck_persona_email_format",
        ),
    )


# ==========================================
# 4. USUARIO
# ==========================================
class Usuario(Base):
    __tablename__ = "INV_USUARIO"

    USU_Usuario = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)

    USU_Username = Column(String(50), unique=True, nullable=False, index=True)
    # Passlib (argon2/bcrypt) embebe el salt dentro del hash. NO almacenar salt aparte.
    USU_Password_Hash = Column(String(255), nullable=False)

    USU_Ultimo_Login = Column(DateTime, nullable=True)
    USU_Rol = Column(String(20), nullable=False)
    USU_Estado = Column(Boolean, default=True, nullable=False)

    # Account lockout
    USU_Intentos_Fallidos = Column(Integer, default=0, nullable=False)
    USU_Bloqueado_Hasta = Column(DateTime, nullable=True)
    USU_Password_Cambiada_En = Column(DateTime, nullable=True)

    PER_Persona = Column(
        Uuid,
        ForeignKey("INV_PERSONA.PER_Persona", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )

    persona = relationship("Persona", back_populates="usuario")

    __table_args__ = (
        CheckConstraint(
            "\"USU_Rol\" IN ('SUPER_ADMIN', 'ADMIN_TI', 'TECNICO', 'CONSULTA')",
            name="ck_usuario_rol_valido",
        ),
    )
