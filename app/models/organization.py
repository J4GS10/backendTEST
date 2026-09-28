import uuid
from sqlalchemy import false
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

    # Jefe inmediato (poblado por la sincronización con Active Directory).
    PER_Jefe = Column(
        Uuid,
        ForeignKey("INV_PERSONA.PER_Persona", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Vínculo con Active Directory: objectGUID estable + DN (para resolver `manager`).
    PER_AD_GUID = Column(String(36), unique=True, nullable=True, index=True)
    PER_AD_DN = Column(String(500), nullable=True)
    PER_AD_Sincronizado_En = Column(DateTime, nullable=True)

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
    # Sede donde trabaja la persona: define qué usuarios con alcance por sede
    # la ven (ver app/core/data_scope.py). NULL = solo alcance global.
    SED_Sede = Column(
        Integer,
        ForeignKey("INV_SEDE.SED_Sede", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())

    departamento = relationship("Departamento", back_populates="personas")
    sede = relationship("app.models.location.Sede")
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
    USU_Password_Hash = Column(String(255), nullable=True)

    USU_Ultimo_Login = Column(DateTime, nullable=True)
    USU_Rol = Column(String(20), nullable=False)
    USU_Estado = Column(Boolean, default=True, nullable=False)
    USU_SSO_Habilitado = Column(Boolean, default=False, nullable=False)
    USU_SSO_Provider = Column(String(20), nullable=True)

    # Account lockout
    USU_Intentos_Fallidos = Column(Integer, default=0, nullable=False)
    USU_Bloqueado_Hasta = Column(DateTime, nullable=True)
    USU_Password_Cambiada_En = Column(DateTime, nullable=True)
    # Contraseña temporal asignada por un administrador: debe cambiarse en el
    # próximo inicio de sesión (la sesión queda restringida hasta hacerlo).
    USU_Debe_Cambiar_Password = Column(Boolean, default=False, nullable=False, server_default=false())

    # 2FA / MFA. Método 'TOTP' (app) o 'EMAIL' (código por correo). El secreto
    # TOTP se guarda cifrado (Fernet); EMAIL no usa secreto persistente.
    USU_2FA_Habilitado = Column(Boolean, default=False, nullable=False)
    USU_2FA_Metodo = Column(String(10), nullable=True)
    USU_2FA_Secret = Column(String(255), nullable=True)
    # Último paso TOTP aceptado: un código ya usado no se acepta de nuevo (anti-replay).
    USU_2FA_Ultimo_Paso = Column(Integer, nullable=True)

    # Alcance de datos (RLS por sede). Global = todas las sedes; si no, solo
    # las de INV_USUARIO_SEDE. SUPER_ADMIN y ADMIN_SEGURIDAD son siempre globales.
    USU_Alcance_Global = Column(Boolean, default=False, nullable=False, server_default=false())
    USU_Creado_En = Column(DateTime, server_default=func.now(), nullable=True)

    PER_Persona = Column(
        Uuid,
        ForeignKey("INV_PERSONA.PER_Persona", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )

    persona = relationship("Persona", back_populates="usuario")
    sedes = relationship(
        "app.models.location.Sede", secondary="INV_USUARIO_SEDE", lazy="selectin",
        order_by="app.models.location.Sede.SED_Nombre",
    )

    @property
    def mfa_requerido(self) -> bool:
        """El rol exige MFA (las cuentas SSO lo delegan en el proveedor de identidad)."""
        from app.services.twofactor import role_requires_2fa
        return role_requires_2fa(self.USU_Rol) and not self.USU_SSO_Habilitado

    @property
    def alcance_global_efectivo(self) -> bool:
        """Ve todas las sedes (por rol de gobierno o por alcance global otorgado)."""
        from app.core.data_scope import user_is_global
        return user_is_global(self)

    __table_args__ = (
        CheckConstraint(
            "\"USU_Rol\" IN ('SUPER_ADMIN', 'ADMIN_SEGURIDAD', 'ADMIN_TI', 'TECNICO', 'AUDITOR', 'CONSULTA')",
            name="ck_usuario_rol_valido",
        ),
        CheckConstraint(
            "\"USU_2FA_Metodo\" IS NULL OR \"USU_2FA_Metodo\" IN ('TOTP', 'EMAIL')",
            name="ck_usuario_2fa_metodo_valido",
        ),
        CheckConstraint(
            "\"USU_SSO_Provider\" IS NULL OR \"USU_SSO_Provider\" IN ('microsoft', 'google')",
            name="ck_usuario_sso_provider_valido",
        ),
    )


# ==========================================
# 5. ALCANCE DE DATOS POR SEDE
# ==========================================
class UsuarioSede(Base):
    """Sedes cuyos datos puede ver un usuario sin alcance global."""
    __tablename__ = "INV_USUARIO_SEDE"

    USU_Usuario = Column(
        Uuid, ForeignKey("INV_USUARIO.USU_Usuario", ondelete="CASCADE"), primary_key=True,
    )
    SED_Sede = Column(
        Integer, ForeignKey("INV_SEDE.SED_Sede", ondelete="CASCADE"), primary_key=True, index=True,
    )
