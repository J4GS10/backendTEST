"""
Roles del sistema y reglas de gobierno de identidades (fuente única).

Separación de funciones:
- SUPER_ADMIN      configuración del sistema y cualquier identidad.
- ADMIN_SEGURIDAD  identidades y accesos: crear usuarios, asignar roles
                   operativos, restablecer contraseñas y MFA, desbloquear,
                   cerrar sesiones, leer la auditoría. Sin acceso al inventario.
- ADMIN_TI / TECNICO / CONSULTA  operación del inventario (sin gestión de usuarios).
- AUDITOR          solo lectura del inventario, más la bitácora de auditoría y
                   su exportación. Sin ninguna operación de escritura.

Alcance de datos (ver app/core/data_scope.py): SUPER_ADMIN y ADMIN_SEGURIDAD
son siempre globales; el resto ve las sedes que se le asignen, o todas si un
SUPER_ADMIN le otorga alcance global.
"""
from __future__ import annotations

SUPER_ADMIN = "SUPER_ADMIN"
ADMIN_SEGURIDAD = "ADMIN_SEGURIDAD"
ADMIN_TI = "ADMIN_TI"
TECNICO = "TECNICO"
AUDITOR = "AUDITOR"
CONSULTA = "CONSULTA"

ALL_ROLES: tuple[str, ...] = (SUPER_ADMIN, ADMIN_SEGURIDAD, ADMIN_TI, TECNICO, AUDITOR, CONSULTA)
ROLE_PATTERN = "^(" + "|".join(ALL_ROLES) + ")$"

# Quién administra identidades.
IAM_ROLES: tuple[str, ...] = (SUPER_ADMIN, ADMIN_SEGURIDAD)
# Quién lee la bitácora de auditoría (el auditor, filtrada por su alcance).
AUDIT_READER_ROLES: tuple[str, ...] = (SUPER_ADMIN, ADMIN_SEGURIDAD, AUDITOR)
# Roles con alcance global implícito (no se limitan por sede).
ALWAYS_GLOBAL_ROLES: tuple[str, ...] = (SUPER_ADMIN, ADMIN_SEGURIDAD)
# Roles del inventario a los que se asigna alcance (global o por sedes).
SCOPED_ROLES: tuple[str, ...] = (ADMIN_TI, TECNICO, AUDITOR, CONSULTA)
# Roles que solo un SUPER_ADMIN puede otorgar o administrar (evita que un
# administrador de seguridad se perpetúe o eleve a otros a su mismo nivel).
PROTECTED_ROLES: tuple[str, ...] = (SUPER_ADMIN, ADMIN_SEGURIDAD)


def can_manage(requester_role: str, target_role: str) -> bool:
    """¿Puede `requester_role` administrar una cuenta con `target_role`?"""
    if requester_role == SUPER_ADMIN:
        return True
    if requester_role == ADMIN_SEGURIDAD:
        return target_role not in PROTECTED_ROLES
    return False


def can_grant(requester_role: str, role: str) -> bool:
    """¿Puede `requester_role` asignar `role` a una cuenta?"""
    return can_manage(requester_role, role)


def can_grant_global_scope(requester_role: str) -> bool:
    """Solo un SUPER_ADMIN otorga alcance global (ver datos de todas las sedes)."""
    return requester_role == SUPER_ADMIN
