"""
Historial de contraseñas: impide reutilizar la actual ni ninguna de las
últimas PASSWORD_HISTORY_COUNT. Se guardan solo los hashes (argon2/bcrypt).
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.models.governance import PasswordHistorial


def personal_data(user) -> list[str]:
    """Datos del titular que la contraseña no puede contener."""
    per = getattr(user, "persona", None)
    if per is None:
        return []
    email_local = (per.PER_Email_Corporativo or "").split("@")[0]
    parts = [per.PER_Primer_Nombre, per.PER_Segundo_Nombre, per.PER_Primer_Apellido,
             per.PER_Segundo_Apellido, email_local]
    # También las partes del correo separadas por punto o guion (juan.perez).
    for sep in (".", "_", "-"):
        parts += email_local.split(sep)
    return [p for p in parts if p]


def validate_new_password(user, new_password: str) -> None:
    """Política completa (longitud, clases, listas de bloqueo y datos personales)."""
    try:
        security.validate_password_policy(
            new_password, username=user.USU_Username, personal_data=personal_data(user),
        )
    except security.PasswordPolicyError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def ensure_not_reused(db: AsyncSession, user, new_password: str) -> None:
    """400 PASSWORD_SAME_AS_OLD / PASSWORD_REUSED si coincide con la actual o una reciente."""
    if user.USU_Password_Hash and security.verify_password(new_password, user.USU_Password_Hash):
        raise HTTPException(status_code=400, detail="PASSWORD_SAME_AS_OLD")
    n = settings.PASSWORD_HISTORY_COUNT
    if n <= 0:
        return
    hashes = (await db.execute(
        select(PasswordHistorial.PWH_Hash)
        .where(PasswordHistorial.USU_Usuario == user.USU_Usuario)
        .order_by(PasswordHistorial.PWH_Creado_En.desc())
        .limit(n)
    )).scalars().all()
    if any(security.verify_password(new_password, h) for h in hashes):
        raise HTTPException(status_code=400, detail=f"PASSWORD_REUSED:{n}")


async def remember_current(db: AsyncSession, user) -> None:
    """
    Guarda el hash VIGENTE en el historial antes de reemplazarlo y recorta el
    historial a las N entradas más recientes.
    """
    if not user.USU_Password_Hash:
        return
    n = settings.PASSWORD_HISTORY_COUNT
    if n <= 0:
        return
    db.add(PasswordHistorial(USU_Usuario=user.USU_Usuario, PWH_Hash=user.USU_Password_Hash))
    await db.flush()
    keep = (await db.execute(
        select(PasswordHistorial.PWH_Id)
        .where(PasswordHistorial.USU_Usuario == user.USU_Usuario)
        .order_by(PasswordHistorial.PWH_Creado_En.desc())
        .limit(n)
    )).scalars().all()
    await db.execute(
        delete(PasswordHistorial)
        .where(PasswordHistorial.USU_Usuario == user.USU_Usuario, PasswordHistorial.PWH_Id.not_in(keep))
        .execution_options(synchronize_session=False)
    )
