"""
Sugerencias relacionales para autocompletar formularios.

Cuando el usuario elige una entidad (persona, activo, modelo, departamento),
el sistema propone los datos que se derivan de ella: departamento, cargo, jefe,
área habitual, custodio actual, marca, tipo, rol, usuario… Cada sugerencia
lleva su `origen` para que la UI explique POR QUÉ se propone (y el usuario
pueda cambiarla). Nunca se sugiere un rol privilegiado (SUPER_ADMIN,
ADMIN_SEGURIDAD): los roles sugeridos son operativos.

Alcance por sede: todas las consultas pasan por el filtro automático de
app/core/data_scope.py, y además un área o una sede solo se SUGIEREN si están
en el alcance del usuario (el historial de una persona puede incluir áreas de
otra sede). Los datos de cuenta (usuario, rol) solo los ve quien gestiona
identidades.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_scope import area_sede_id, current_scope, default_sede_id
from app.core.roles import IAM_ROLES, PROTECTED_ROLES
from app.models.location import Sede
from app.models.catalogs import Marca, Modelo, TipoActivo
from app.models.core import Activo
from app.models.location import Area
from app.models.organization import Cargo, Departamento, Persona, Usuario
from app.models.traceability import Movimiento


def _nombre(p: Persona | None) -> str | None:
    return f"{p.PER_Primer_Nombre} {p.PER_Primer_Apellido}".strip() if p else None


def _persona_ref(p: Persona | None) -> dict | None:
    if p is None:
        return None
    return {"PER_Persona": str(p.PER_Persona), "nombre": _nombre(p), "email": p.PER_Email_Corporativo}


def _slug_username(email: str | None, nombre: str, apellido: str) -> str:
    base = (email or "").split("@")[0] or f"{nombre}.{apellido}"
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9._-]", "", base).strip("._-")
    return (base or "usuario")[:40]


class SuggestionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Consultas auxiliares
    # ------------------------------------------------------------------
    @staticmethod
    def _en_alcance(sede_id: int | None) -> bool:
        scope = current_scope()
        return scope is None or scope.allows(sede_id)

    async def _area_ref(self, area_id: int | None, origen: str, *, solo_alcance: bool = True) -> dict | None:
        """Referencia a un área; como sugerencia, solo si su sede está en el alcance."""
        if not area_id:
            return None
        area = await self.db.get(Area, area_id)
        if not area:
            return None
        sede = await area_sede_id(self.db, area_id)
        if solo_alcance and not self._en_alcance(sede):
            return None
        return {"ARE_Area": area.ARE_Area, "nombre": area.ARE_Nombre, "SED_Sede": sede, "origen": origen}

    async def _sede_ref(self, sede_id: int | None, origen: str) -> dict | None:
        if sede_id is None or not self._en_alcance(sede_id):
            return None
        sede = await self.db.get(Sede, sede_id)
        return {"SED_Sede": sede.SED_Sede, "nombre": sede.SED_Nombre, "origen": origen} if sede else None

    async def _area_frecuente_departamento(self, dep_id: int) -> int | None:
        """Área más usada por el departamento, entre las del alcance."""
        rows = (await self.db.execute(
            select(Movimiento.ARE_Area, func.count().label("n"))
            .join(Persona, Persona.PER_Persona == Movimiento.PER_Persona)
            .where(Persona.DEP_Departamento == dep_id, Movimiento.ARE_Area.is_not(None))
            .group_by(Movimiento.ARE_Area).order_by(desc("n")).limit(10)
        )).all()
        for area_id, _ in rows:
            if self._en_alcance(await area_sede_id(self.db, area_id)):
                return area_id
        return None

    async def _jefe_departamento(self, dep_id: int, excluir: uuid.UUID | None = None) -> Persona | None:
        """Persona activa con cargo de jefatura en el departamento; si no hay, el jefe más común."""
        q = (select(Persona).join(Cargo, Cargo.CAR_Cargo == Persona.CAR_Cargo)
             .where(Persona.DEP_Departamento == dep_id, Persona.PER_Estado.is_(True), Cargo.CAR_Es_Jefatura.is_(True)))
        if excluir:
            q = q.where(Persona.PER_Persona != excluir)
        jefe = (await self.db.execute(q.limit(1))).scalars().first()
        if jefe:
            return jefe
        row = (await self.db.execute(
            select(Persona.PER_Jefe, func.count().label("n"))
            .where(Persona.DEP_Departamento == dep_id, Persona.PER_Jefe.is_not(None))
            .group_by(Persona.PER_Jefe).order_by(desc("n")).limit(1)
        )).first()
        if row and row[0] != excluir:
            return await self.db.get(Persona, row[0])
        return None

    async def _rol_frecuente(self, campo, valor) -> str | None:
        row = (await self.db.execute(
            select(Usuario.USU_Rol, func.count().label("n"))
            .join(Persona, Persona.PER_Persona == Usuario.PER_Persona)
            .where(campo == valor, Usuario.USU_Estado.is_(True), Usuario.USU_Rol.not_in(PROTECTED_ROLES))
            .group_by(Usuario.USU_Rol).order_by(desc("n")).limit(1)
        )).first()
        return row[0] if row else None

    async def _username_libre(self, base: str) -> str:
        existentes = set((await self.db.execute(
            select(Usuario.USU_Username).where(Usuario.USU_Username.like(f"{base}%"))
        )).scalars())
        if base not in existentes:
            return base
        n = 2
        while f"{base}{n}" in existentes:
            n += 1
        return f"{base}{n}"

    # ------------------------------------------------------------------
    # Persona
    # ------------------------------------------------------------------
    async def persona(self, persona_id: uuid.UUID) -> dict[str, Any]:
        p = await self.db.get(Persona, persona_id)
        if not p:
            raise HTTPException(404, "PERSON_NOT_FOUND")
        dep = await self.db.get(Departamento, p.DEP_Departamento)
        car = await self.db.get(Cargo, p.CAR_Cargo)
        jefe = await self.db.get(Persona, p.PER_Jefe) if p.PER_Jefe else await self._jefe_departamento(p.DEP_Departamento, excluir=p.PER_Persona)

        # Área: la del último movimiento de la persona dentro del alcance; si no
        # tiene, la más usada en su departamento.
        ultimas = (await self.db.execute(
            select(Movimiento.ARE_Area).where(Movimiento.PER_Persona == persona_id, Movimiento.ARE_Area.is_not(None))
            .order_by(desc(Movimiento.MOV_Fecha_Asignacion)).limit(10)
        )).scalars().all()
        area = None
        for area_id in ultimas:
            area = await self._area_ref(area_id, "ultima_asignacion")
            if area:
                break
        if area is None:
            area = await self._area_ref(await self._area_frecuente_departamento(p.DEP_Departamento), "departamento")

        vigentes = (await self.db.execute(
            select(Activo.ACT_Codigo_Interno).join(Movimiento, Movimiento.ACT_Activo == Activo.ACT_Activo)
            .where(Movimiento.PER_Persona == persona_id, Movimiento.MOV_Fecha_Devolucion.is_(None))
        )).scalars().all()

        # Sede: la de la persona; si no tiene, la del área sugerida; si el
        # usuario tiene una sola sede, esa.
        sede = (
            await self._sede_ref(p.SED_Sede, "persona")
            or await self._sede_ref(area["SED_Sede"] if area else None, "area")
            or await self._sede_ref(default_sede_id(), "alcance")
        )

        base = {
            "persona": _persona_ref(p),
            "departamento": {"DEP_Departamento": dep.DEP_Departamento, "nombre": dep.DEP_Nombre} if dep else None,
            "cargo": {"CAR_Cargo": car.CAR_Cargo, "nombre": car.CAR_Nombre} if car else None,
            "jefe": {**_persona_ref(jefe), "origen": "registrado" if p.PER_Jefe else "departamento"} if jefe else None,
            "area_sugerida": area,
            "sede_sugerida": sede,
            "activos_vigentes": list(vigentes),
            "usuario": None,
            "username_sugerido": None,
            "rol_sugerido": None,
            "alcance_sugerido": None,
        }
        # Datos de cuenta: solo para quien gestiona identidades.
        scope = current_scope()
        if scope is not None and scope.rol not in IAM_ROLES:
            return base

        usuario = (await self.db.execute(select(Usuario).where(Usuario.PER_Persona == persona_id))).scalar_one_or_none()
        rol, origen_rol = await self._rol_frecuente(Persona.CAR_Cargo, p.CAR_Cargo), "cargo"
        if not rol:
            rol, origen_rol = await self._rol_frecuente(Persona.DEP_Departamento, p.DEP_Departamento), "departamento"
        if not rol:
            rol, origen_rol = "CONSULTA", "minimo_privilegio"

        return {
            **base,
            "usuario": {"USU_Usuario": str(usuario.USU_Usuario), "username": usuario.USU_Username,
                        "rol": usuario.USU_Rol} if usuario else None,
            "username_sugerido": None if usuario else await self._username_libre(
                _slug_username(p.PER_Email_Corporativo, p.PER_Primer_Nombre, p.PER_Primer_Apellido)),
            "rol_sugerido": None if usuario else {"rol": rol, "origen": origen_rol},
            # Mínimo privilegio: el alcance sugerido es la sede de la persona, nunca global.
            "alcance_sugerido": None if usuario or not sede else {"sedes": [sede["SED_Sede"]], "origen": sede["origen"]},
        }

    # ------------------------------------------------------------------
    # Departamento (alta de persona)
    # ------------------------------------------------------------------
    async def departamento(self, dep_id: int) -> dict[str, Any]:
        dep = await self.db.get(Departamento, dep_id)
        if not dep:
            raise HTTPException(404, "DEPARTMENT_NOT_FOUND")
        row = (await self.db.execute(
            select(Persona.CAR_Cargo, func.count().label("n")).where(Persona.DEP_Departamento == dep_id)
            .group_by(Persona.CAR_Cargo).order_by(desc("n")).limit(1)
        )).first()
        cargo = await self.db.get(Cargo, row[0]) if row else None
        jefe = await self._jefe_departamento(dep_id)
        area = await self._area_ref(await self._area_frecuente_departamento(dep_id), "departamento")
        return {
            "cargo_sugerido": {"CAR_Cargo": cargo.CAR_Cargo, "nombre": cargo.CAR_Nombre, "origen": "departamento"} if cargo else None,
            "jefe_sugerido": {**_persona_ref(jefe), "origen": "departamento"} if jefe else None,
            "area_sugerida": area,
            # Sede para la persona nueva: la del área habitual del departamento
            # o, si el usuario tiene una sola sede, esa.
            "sede_sugerida": (
                await self._sede_ref(area["SED_Sede"] if area else None, "departamento")
                or await self._sede_ref(default_sede_id(), "alcance")
            ),
        }

    # ------------------------------------------------------------------
    # Activo (asignación, devolución, mantenimiento)
    # ------------------------------------------------------------------
    async def activo(self, activo_id: uuid.UUID) -> dict[str, Any]:
        a = await self.db.get(Activo, activo_id)
        if not a:
            raise HTTPException(404, "ASSET_NOT_FOUND")
        mov = (await self.db.execute(
            select(Movimiento).where(Movimiento.ACT_Activo == activo_id, Movimiento.MOV_Fecha_Devolucion.is_(None))
        )).scalars().first()
        custodio = await self.db.get(Persona, mov.PER_Persona) if mov else None
        dep = await self.db.get(Departamento, custodio.DEP_Departamento) if custodio else None
        return {
            "custodio": {**_persona_ref(custodio), "departamento": dep.DEP_Nombre if dep else None} if custodio else None,
            # Ubicación actual del propio activo (informativa, no una sugerencia).
            "area_actual": await self._area_ref(mov.ARE_Area, "movimiento_vigente", solo_alcance=False) if mov else None,
            "sede": await self._sede_ref(a.SED_Sede, "activo"),
            # Asignado → lo lógico es transferir; libre → asignar.
            "tipo_movimiento_sugerido": "transferencia" if mov else "asignacion",
            "hostname": a.ACT_Hostname,
        }

    # ------------------------------------------------------------------
    # Modelo (alta de activo)
    # ------------------------------------------------------------------
    async def modelo(self, modelo_id: int) -> dict[str, Any]:
        m = await self.db.get(Modelo, modelo_id)
        if not m:
            raise HTTPException(404, "MODEL_NOT_FOUND")
        marca = await self.db.get(Marca, m.MAR_Marca)
        row = (await self.db.execute(
            select(Activo.TAC_Tipo_Activo, func.count().label("n")).where(Activo.MOD_Modelo == modelo_id)
            .group_by(Activo.TAC_Tipo_Activo).order_by(desc("n")).limit(1)
        )).first()
        tipo = await self.db.get(TipoActivo, row[0]) if row else None
        return {
            "marca": {"MAR_Marca": marca.MAR_Marca, "nombre": marca.MAR_Nombre} if marca else None,
            "tipo_sugerido": {"TAC_Tipo_Activo": tipo.TAC_Tipo_Activo, "nombre": tipo.TAC_Nombre,
                              "prefijo": tipo.TAC_Prefijo, "origen": "activos_del_modelo"} if tipo else None,
        }
