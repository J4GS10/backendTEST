"""Servicio de Organización (Departamento / Cargo / Persona / Usuario)."""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timezone

from app.core.security import PasswordPolicyError, validate_password_policy
from app.core.transactional import commit_or_409
from app.repositories.governance import GovernanceRepository
from app.repositories.organization import (
    CargoRepository, DepartamentoRepository, PersonaRepository, UsuarioRepository,
)
from app.schemas.organization import (
    CargoCreate, CargoUpdate,
    DepartamentoCreate, DepartamentoUpdate,
    PersonaCreate, PersonaUpdate,
    UsuarioCreate, UsuarioUpdate,
)


class OrganizationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.dep_repo = DepartamentoRepository(db)
        self.car_repo = CargoRepository(db)
        self.per_repo = PersonaRepository(db)
        self.usu_repo = UsuarioRepository(db)
        self.gov_repo = GovernanceRepository(db)

    async def _commit_audit(self, *, accion: str, entidad: str, snapshot: dict, usuario_id, ip):
        await self.gov_repo.create_audit_log(accion, entidad, snapshot, usuario_id=usuario_id, ip_origen=ip)
        await commit_or_409(self.db, where=f"OrganizationService.{entidad}")

    async def get_personas_disponibles(self):
        return await self.per_repo.get_available_for_user()

    # =====================================================================
    # RESUMEN POR DEPARTAMENTO (vista profesional)
    # =====================================================================
    async def departamentos_resumen(self):
        """
        Para cada departamento devuelve:
        - cantidad de personas activas
        - cantidad de activos asignados actualmente (vía Movimientos abiertos)
        - desglose por tipo de activo
        """
        from sqlalchemy import func as _func, select as _select
        from app.models.catalogs import TipoActivo
        from app.models.core import Activo
        from app.models.organization import Departamento, Persona
        from app.models.traceability import Movimiento

        # 1. Todos los departamentos
        deptos = (await self.db.execute(_select(Departamento).order_by(Departamento.DEP_Nombre))).scalars().all()

        # 2. Conteo de personas por depto
        personas_q = await self.db.execute(
            _select(Persona.DEP_Departamento, _func.count(Persona.PER_Persona))
            .where(Persona.PER_Estado.is_(True))
            .group_by(Persona.DEP_Departamento)
        )
        personas_map = {row[0]: row[1] for row in personas_q.all()}

        # 3. Conteo de ACTIVOS asignados a personas de cada depto (via movimientos vigentes)
        activos_q = await self.db.execute(
            _select(Persona.DEP_Departamento, _func.count(Movimiento.ACT_Activo.distinct()))
            .join(Movimiento, Movimiento.PER_Persona == Persona.PER_Persona)
            .where(Movimiento.MOV_Fecha_Devolucion.is_(None))
            .group_by(Persona.DEP_Departamento)
        )
        activos_map = {row[0]: row[1] for row in activos_q.all()}

        # 4. Desglose por tipo de activo por depto
        breakdown_q = await self.db.execute(
            _select(
                Persona.DEP_Departamento,
                TipoActivo.TAC_Nombre,
                _func.count(Movimiento.ACT_Activo.distinct()),
            )
            .join(Movimiento, Movimiento.PER_Persona == Persona.PER_Persona)
            .join(Activo, Activo.ACT_Activo == Movimiento.ACT_Activo)
            .join(TipoActivo, TipoActivo.TAC_Tipo_Activo == Activo.TAC_Tipo_Activo)
            .where(Movimiento.MOV_Fecha_Devolucion.is_(None))
            .group_by(Persona.DEP_Departamento, TipoActivo.TAC_Nombre)
        )
        breakdown_map: dict[int, dict[str, int]] = {}
        for dep_id, tipo_nombre, count in breakdown_q.all():
            breakdown_map.setdefault(dep_id, {})[tipo_nombre] = count

        return [
            {
                "DEP_Departamento": d.DEP_Departamento,
                "DEP_Nombre": d.DEP_Nombre,
                "DEP_Codigo_Costos": d.DEP_Codigo_Costos,
                "DEP_Activo": d.DEP_Activo,
                "personas_activas": personas_map.get(d.DEP_Departamento, 0),
                "activos_asignados": activos_map.get(d.DEP_Departamento, 0),
                "por_tipo": breakdown_map.get(d.DEP_Departamento, {}),
            }
            for d in deptos
        ]

    async def departamento_detalle(self, dep_id: int):
        """
        Detalle completo del departamento: personas + sus activos asignados.
        """
        from sqlalchemy import select as _select
        from sqlalchemy.orm import selectinload
        from app.models.catalogs import Modelo, TipoActivo
        from app.models.core import Activo
        from app.models.organization import Departamento, Persona
        from app.models.traceability import Movimiento

        depto = (await self.db.execute(
            _select(Departamento).where(Departamento.DEP_Departamento == dep_id)
        )).scalar_one_or_none()
        if not depto:
            raise HTTPException(404, "DEPARTMENT_NOT_FOUND")

        # Personas del departamento (activas)
        personas = (await self.db.execute(
            _select(Persona)
            .where(Persona.DEP_Departamento == dep_id, Persona.PER_Estado.is_(True))
            .order_by(Persona.PER_Primer_Apellido)
        )).scalars().all()

        per_ids = [p.PER_Persona for p in personas]
        movimientos = []
        if per_ids:
            movimientos = (await self.db.execute(
                _select(Movimiento)
                .options(
                    selectinload(Movimiento.activo).selectinload(Activo.modelo).selectinload(Modelo.marca),
                    selectinload(Movimiento.activo).selectinload(Activo.tipo_activo),
                    selectinload(Movimiento.area),
                )
                .where(Movimiento.PER_Persona.in_(per_ids), Movimiento.MOV_Fecha_Devolucion.is_(None))
            )).scalars().all()

        # Agrupar movimientos por persona
        mov_por_persona: dict = {}
        for m in movimientos:
            mov_por_persona.setdefault(m.PER_Persona, []).append({
                "MOV_Movimiento": str(m.MOV_Movimiento),
                "MOV_Fecha_Asignacion": m.MOV_Fecha_Asignacion.isoformat() if m.MOV_Fecha_Asignacion else None,
                "activo": {
                    "ACT_Activo": str(m.activo.ACT_Activo),
                    "ACT_Codigo_Interno": m.activo.ACT_Codigo_Interno,
                    "ACT_Hostname": m.activo.ACT_Hostname,
                    "ACT_Serie_Fabricante": m.activo.ACT_Serie_Fabricante,
                    "tipo": m.activo.tipo_activo.TAC_Nombre if m.activo.tipo_activo else None,
                    "modelo": m.activo.modelo.MOD_Nombre if m.activo.modelo else None,
                    "marca": m.activo.modelo.marca.MAR_Nombre if m.activo.modelo and m.activo.modelo.marca else None,
                } if m.activo else None,
                "area": m.area.ARE_Nombre if m.area else None,
            })

        return {
            "DEP_Departamento": depto.DEP_Departamento,
            "DEP_Nombre": depto.DEP_Nombre,
            "DEP_Codigo_Costos": depto.DEP_Codigo_Costos,
            "DEP_Descripcion": depto.DEP_Descripcion,
            "DEP_Activo": depto.DEP_Activo,
            "personas": [
                {
                    "PER_Persona": str(p.PER_Persona),
                    "nombre_completo": f"{p.PER_Primer_Nombre} {p.PER_Primer_Apellido}",
                    "PER_Email_Corporativo": p.PER_Email_Corporativo,
                    "PER_Telefono": p.PER_Telefono,
                    "PER_Estado": p.PER_Estado,
                    "activos_asignados": mov_por_persona.get(p.PER_Persona, []),
                }
                for p in personas
            ],
            "totales": {
                "personas": len(personas),
                "activos": sum(len(v) for v in mov_por_persona.values()),
            },
        }

    # =====================================================================
    # DEPARTAMENTO
    # =====================================================================
    async def get_departamentos(self):
        return await self.dep_repo.get_all()

    async def get_departamento(self, id: int):
        obj = await self.dep_repo.get_by_id(id)
        if not obj:
            raise HTTPException(404, "DEPARTMENT_NOT_FOUND")
        return obj

    async def create_departamento(self, schema: DepartamentoCreate, usuario_id=None, ip=None):
        if await self.dep_repo.get_by_name(schema.DEP_Nombre):
            raise HTTPException(400, "DEPARTMENT_ALREADY_EXISTS")
        obj = await self.dep_repo.create(schema)
        await self._commit_audit(
            accion="CREATE", entidad="INV_DEPARTAMENTO",
            snapshot={"nombre": schema.DEP_Nombre},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def update_departamento(self, id: int, schema: DepartamentoUpdate, usuario_id=None, ip=None):
        await self.get_departamento(id)
        obj = await self.dep_repo.update(id, schema)
        await self._commit_audit(
            accion="UPDATE", entidad="INV_DEPARTAMENTO",
            snapshot={"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def delete_departamento(self, id: int, usuario_id=None, ip=None):
        dep = await self.get_departamento(id)
        if await self.dep_repo.count_personas(id) > 0:
            raise HTTPException(409, "CANNOT_DELETE_DEPARTMENT_HAS_PERSONS")
        await self.dep_repo.delete(id)
        await self._commit_audit(
            accion="DELETE", entidad="INV_DEPARTAMENTO",
            snapshot={"id": id, "nombre": dep.DEP_Nombre},
            usuario_id=usuario_id, ip=ip,
        )

    # =====================================================================
    # CARGO
    # =====================================================================
    async def get_cargos(self):
        return await self.car_repo.get_all()

    async def get_cargo(self, id: int):
        obj = await self.car_repo.get_by_id(id)
        if not obj:
            raise HTTPException(404, "POSITION_NOT_FOUND")
        return obj

    async def create_cargo(self, schema: CargoCreate, usuario_id=None, ip=None):
        obj = await self.car_repo.create(schema)
        await self._commit_audit(
            accion="CREATE", entidad="INV_CARGO",
            snapshot={"nombre": schema.CAR_Nombre},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def update_cargo(self, id: int, schema: CargoUpdate, usuario_id=None, ip=None):
        await self.get_cargo(id)
        obj = await self.car_repo.update(id, schema)
        await self._commit_audit(
            accion="UPDATE", entidad="INV_CARGO",
            snapshot={"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def delete_cargo(self, id: int, usuario_id=None, ip=None):
        cargo = await self.get_cargo(id)
        if await self.car_repo.count_personas(id) > 0:
            raise HTTPException(409, "CANNOT_DELETE_POSITION_HAS_PERSONS")
        await self.car_repo.delete(id)
        await self._commit_audit(
            accion="DELETE", entidad="INV_CARGO",
            snapshot={"id": id, "nombre": cargo.CAR_Nombre},
            usuario_id=usuario_id, ip=ip,
        )

    # =====================================================================
    # PERSONA
    # =====================================================================
    async def get_personas(self):
        return await self.per_repo.get_all()

    async def get_persona(self, id: uuid.UUID):
        obj = await self.per_repo.get_by_id(id)
        if not obj:
            raise HTTPException(404, "PERSON_NOT_FOUND")
        return obj

    async def create_persona(self, schema: PersonaCreate, usuario_id=None, ip=None):
        if await self.per_repo.get_by_email(schema.PER_Email_Corporativo):
            raise HTTPException(400, "EMAIL_ALREADY_EXISTS")
        obj = await self.per_repo.create(schema)
        await self._commit_audit(
            accion="CREATE", entidad="INV_PERSONA",
            snapshot={
                "email": schema.PER_Email_Corporativo,
                "nombre": f"{schema.PER_Primer_Nombre} {schema.PER_Primer_Apellido}",
            },
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def update_persona(self, id: uuid.UUID, schema: PersonaUpdate, usuario_id=None, ip=None):
        await self.get_persona(id)
        obj = await self.per_repo.update(id, schema)
        await self._commit_audit(
            accion="UPDATE", entidad="INV_PERSONA",
            snapshot={"id": str(id), "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def delete_persona(self, id: uuid.UUID, usuario_id=None, ip=None):
        persona = await self.get_persona(id)
        if await self.per_repo.has_usuario(id):
            raise HTTPException(409, "CANNOT_DELETE_PERSON_HAS_USER_ACCOUNT")
        await self.per_repo.update(id, PersonaUpdate(PER_Estado=False))
        await self._commit_audit(
            accion="DELETE_LOGIC", entidad="INV_PERSONA",
            snapshot={"id": str(id), "email": persona.PER_Email_Corporativo},
            usuario_id=usuario_id, ip=ip,
        )

    # =====================================================================
    # USUARIO — Reglas: SUPER_ADMIN crea cualquier rol; ADMIN_TI no crea otros admins.
    # =====================================================================
    async def get_usuarios(self):
        return await self.usu_repo.get_all()

    async def get_usuario(self, id: uuid.UUID):
        obj = await self.usu_repo.get_by_id(id)
        if not obj:
            raise HTTPException(404, "USER_NOT_FOUND")
        return obj

    async def create_usuario(
        self, schema: UsuarioCreate, requester_role: str, usuario_id=None, ip=None
    ):
        if schema.USU_Rol in ("SUPER_ADMIN", "ADMIN_TI") and requester_role != "SUPER_ADMIN":
            raise HTTPException(403, "ONLY_SUPER_ADMIN_CAN_CREATE_ADMINS")

        # Política de contraseña
        try:
            validate_password_policy(schema.USU_Password, username=schema.USU_Username)
        except PasswordPolicyError as e:
            raise HTTPException(400, str(e))

        if not await self.per_repo.get_by_id(schema.PER_Persona):
            raise HTTPException(404, "PERSONA_NOT_FOUND")

        if await self.usu_repo.get_by_username(schema.USU_Username):
            raise HTTPException(400, "USERNAME_ALREADY_EXISTS")

        # Una persona = un usuario (UNIQUE en BD, validamos antes para mejor error)
        if await self.per_repo.has_usuario(schema.PER_Persona):
            raise HTTPException(400, "PERSON_ALREADY_HAS_USER")

        obj = await self.usu_repo.create(schema)
        await self._commit_audit(
            accion="CREATE", entidad="INV_USUARIO",
            snapshot={"username": schema.USU_Username, "rol": schema.USU_Rol},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def update_usuario(
        self, usuario_id_target: uuid.UUID, schema: UsuarioUpdate,
        requester_role: str, usuario_id=None, ip=None,
    ):
        target = await self.get_usuario(usuario_id_target)

        # Protección de jerarquía
        if target.USU_Rol == "SUPER_ADMIN" and requester_role != "SUPER_ADMIN":
            raise HTTPException(403, "CANNOT_MODIFY_SUPER_ADMIN")
        if requester_role == "ADMIN_TI" and target.USU_Rol in ("SUPER_ADMIN", "ADMIN_TI"):
            raise HTTPException(403, "INSUFFICIENT_PERMISSIONS")

        # Protección del último super-admin
        will_disable = schema.USU_Estado is False
        will_demote = bool(schema.USU_Rol) and schema.USU_Rol != "SUPER_ADMIN"
        if target.USU_Rol == "SUPER_ADMIN" and (will_disable or will_demote):
            count = await self.usu_repo.count_active_super_admins()
            if count <= 1:
                raise HTTPException(400, "CANNOT_DISABLE_LAST_SUPER_ADMIN")

        # Política de contraseña si viene cambio
        if schema.USU_Password:
            try:
                validate_password_policy(schema.USU_Password, username=target.USU_Username)
            except PasswordPolicyError as e:
                raise HTTPException(400, str(e))
            # Revocar todos los tokens emitidos al usuario (deja de aceptar los viejos)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            # Expira muy tarde: 30 días — suficiente para cubrir refresh
            await self.gov_repo.revoke_all_user_tokens(usuario_id_target, expira=now.replace(year=now.year + 1))

        obj = await self.usu_repo.update(usuario_id_target, schema)
        await self._commit_audit(
            accion="UPDATE", entidad="INV_USUARIO",
            snapshot={
                "target_id": str(usuario_id_target),
                "cambios": schema.model_dump(exclude_unset=True, exclude={"USU_Password"}),
                "password_cambiada": bool(schema.USU_Password),
            },
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def desactivar_usuario(
        self, usuario_id_target: uuid.UUID, requester_role: str, usuario_id=None, ip=None,
    ):
        """Desactivación lógica (no borrado físico — preserva auditoría)."""
        return await self.update_usuario(
            usuario_id_target,
            UsuarioUpdate(USU_Estado=False),
            requester_role=requester_role,
            usuario_id=usuario_id,
            ip=ip,
        )
