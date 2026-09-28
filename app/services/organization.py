"""Servicio de Organización (Departamento / Cargo / Persona / Usuario)."""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timezone

from app.core import roles
from app.core.data_scope import elevated, require_owned, require_sede, strict_sede_clause
from app.core.security import generate_temporary_password, get_password_hash
from app.models.organization import Persona
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
from app.services.base import BaseService


def _far_future() -> datetime:
    """Vigencia del registro de revocación global (cubre cualquier refresh vivo)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now.replace(year=now.year + 1)


class OrganizationService(BaseService[DepartamentoRepository]):
    repo_class = DepartamentoRepository

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.dep_repo = DepartamentoRepository(db)
        self.car_repo = CargoRepository(db)
        self.per_repo = PersonaRepository(db)
        self.usu_repo = UsuarioRepository(db)
        self.gov_repo = GovernanceRepository(db)

    async def _commit_audit(self, *, accion: str, entidad: str, snapshot: dict, usuario_id, ip, sede=None):
        await self.gov_repo.create_audit_log(
            accion, entidad, snapshot, usuario_id=usuario_id, ip_origen=ip, sede_id=sede,
        )
        await commit_or_409(self.db, where=f"OrganizationService.{entidad}")

    async def get_personas_disponibles(self):
        return await self.per_repo.get_available_for_user(strict_sede_clause(Persona.SED_Sede))

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
        strict = strict_sede_clause(Persona.SED_Sede)
        personas_stmt = (
            _select(Persona.DEP_Departamento, _func.count(Persona.PER_Persona))
            .where(Persona.PER_Estado.is_(True))
            .group_by(Persona.DEP_Departamento)
        )
        if strict is not None:
            personas_stmt = personas_stmt.where(strict)
        personas_q = await self.db.execute(personas_stmt)
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
        from app.models.catalogs import Modelo
        from app.models.core import Activo
        from app.models.organization import Departamento, Persona
        from app.models.traceability import Movimiento

        depto = (await self.db.execute(
            _select(Departamento).where(Departamento.DEP_Departamento == dep_id)
        )).scalar_one_or_none()
        if not depto:
            raise HTTPException(404, "DEPARTMENT_NOT_FOUND")

        # Personas del departamento (activas)
        personas_stmt = (
            _select(Persona)
            .where(Persona.DEP_Departamento == dep_id, Persona.PER_Estado.is_(True))
            .order_by(Persona.PER_Primer_Apellido)
        )
        strict = strict_sede_clause(Persona.SED_Sede)
        if strict is not None:
            personas_stmt = personas_stmt.where(strict)
        personas = (await self.db.execute(personas_stmt)).scalars().all()

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
        # Padrón de personas: solo las de las sedes del alcance (las visibles
        # únicamente por el historial de un activo no se listan).
        return await self.per_repo.get_all(strict_sede_clause(Persona.SED_Sede))

    async def get_persona(self, id: uuid.UUID):
        obj = await self.per_repo.get_by_id(id)
        if not obj:
            raise HTTPException(404, "PERSON_NOT_FOUND")
        return obj

    async def _validate_jefe(self, jefe_id: uuid.UUID | None) -> None:
        if jefe_id is not None and not await self.per_repo.get_by_id(jefe_id):
            raise HTTPException(404, "MANAGER_NOT_FOUND")

    async def create_persona(self, schema: PersonaCreate, usuario_id=None, ip=None):
        schema.SED_Sede = require_sede(schema.SED_Sede, required=False)
        await self._validate_jefe(schema.PER_Jefe)
        # El correo es único en toda la empresa, no solo en el alcance.
        async with elevated(self.db):
            email_existe = await self.per_repo.get_by_email(schema.PER_Email_Corporativo)
        if email_existe:
            raise HTTPException(400, "EMAIL_ALREADY_EXISTS")
        obj = await self.per_repo.create(schema)
        await self._commit_audit(
            accion="CREATE", entidad="INV_PERSONA",
            snapshot={
                "email": schema.PER_Email_Corporativo,
                "nombre": f"{schema.PER_Primer_Nombre} {schema.PER_Primer_Apellido}",
                "sede": schema.SED_Sede,
            },
            usuario_id=usuario_id, ip=ip, sede=schema.SED_Sede,
        )
        return obj

    async def update_persona(self, id: uuid.UUID, schema: PersonaUpdate, usuario_id=None, ip=None):
        persona = await self.get_persona(id)
        # Solo se modifican personas de las sedes del alcance (no las visibles
        # únicamente por el historial de un activo).
        require_owned(persona.SED_Sede)
        if "SED_Sede" in schema.model_fields_set:
            schema.SED_Sede = require_sede(schema.SED_Sede, required=False)
        if schema.PER_Jefe is not None and schema.PER_Jefe == id:
            raise HTTPException(400, "PERSON_CANNOT_BE_OWN_MANAGER")
        await self._validate_jefe(schema.PER_Jefe)
        sede_final = schema.SED_Sede if "SED_Sede" in schema.model_fields_set else persona.SED_Sede
        obj = await self.per_repo.update(id, schema)
        await self._commit_audit(
            accion="UPDATE", entidad="INV_PERSONA",
            snapshot={"id": str(id), "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip=ip, sede=sede_final,
        )
        return obj

    async def delete_persona(self, id: uuid.UUID, usuario_id=None, ip=None):
        persona = await self.get_persona(id)
        require_owned(persona.SED_Sede)
        if await self.per_repo.has_usuario(id):
            raise HTTPException(409, "CANNOT_DELETE_PERSON_HAS_USER_ACCOUNT")
        await self.per_repo.update(id, PersonaUpdate(PER_Estado=False))
        await self._commit_audit(
            accion="DELETE_LOGIC", entidad="INV_PERSONA",
            snapshot={"id": str(id), "email": persona.PER_Email_Corporativo},
            usuario_id=usuario_id, ip=ip, sede=persona.SED_Sede,
        )

    # =====================================================================
    # ALCANCE DE DATOS DE UN USUARIO (sedes / global)
    # =====================================================================
    async def _validated_sedes(self, sede_ids: list[int]) -> list[int]:
        from sqlalchemy import select as _select
        from app.models.location import Sede
        ids = sorted(set(sede_ids))
        if not ids:
            return []
        found = set((await self.db.execute(
            _select(Sede.SED_Sede).where(Sede.SED_Sede.in_(ids))
        )).scalars().all())
        if found != set(ids):
            raise HTTPException(400, "SEDE_NOT_FOUND")
        return ids

    async def _apply_scope(
        self, usuario, *, rol: str, global_: bool | None, sede_ids: list[int] | None,
        requester_role: str,
    ) -> dict:
        """
        Aplica el alcance y devuelve el diff para la auditoría. Reglas:
        - SUPER_ADMIN y ADMIN_SEGURIDAD son globales por rol (se ignora lo enviado).
        - Solo un SUPER_ADMIN otorga el alcance global.
        - Un rol de inventario debe quedar con alcance global o al menos una sede.
        """
        from sqlalchemy import delete as _delete
        from app.models.organization import UsuarioSede

        antes = {
            "global": bool(usuario.USU_Alcance_Global),
            "sedes": sorted(s.SED_Sede for s in (usuario.sedes or [])),
        }
        if rol in roles.ALWAYS_GLOBAL_ROLES:
            global_, sede_ids = False, []
        nuevo_global = antes["global"] if global_ is None else bool(global_)
        if nuevo_global and not antes["global"] and not roles.can_grant_global_scope(requester_role):
            raise HTTPException(403, "ONLY_SUPER_ADMIN_CAN_GRANT_GLOBAL_SCOPE")
        nuevas_sedes = antes["sedes"] if sede_ids is None else await self._validated_sedes(sede_ids)
        if nuevo_global:
            nuevas_sedes = []
        if rol in roles.SCOPED_ROLES and not nuevo_global and not nuevas_sedes:
            raise HTTPException(400, "SCOPE_REQUIRED")

        usuario.USU_Alcance_Global = nuevo_global
        if nuevas_sedes != antes["sedes"]:
            await self.db.execute(
                _delete(UsuarioSede).where(UsuarioSede.USU_Usuario == usuario.USU_Usuario)
            )
            for sede_id in nuevas_sedes:
                self.db.add(UsuarioSede(USU_Usuario=usuario.USU_Usuario, SED_Sede=sede_id))
            await self.db.flush()
            await self.db.refresh(usuario, attribute_names=["sedes"])
        despues = {"global": nuevo_global, "sedes": nuevas_sedes}
        return {"antes": antes, "despues": despues} if antes != despues else {}

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
        # SUPER_ADMIN otorga cualquier rol; ADMIN_SEGURIDAD solo roles operativos.
        if not roles.can_grant(requester_role, schema.USU_Rol):
            raise HTTPException(403, "ONLY_SUPER_ADMIN_CAN_CREATE_ADMINS")

        # Política de contraseña
        if not schema.USU_Password and not schema.USU_SSO_Habilitado:
            raise HTTPException(400, "AUTH_METHOD_REQUIRED")
        if schema.USU_SSO_Provider and not schema.USU_SSO_Habilitado:
            raise HTTPException(400, "SSO_PROVIDER_REQUIRES_SSO_ENABLED")
        persona = await self.per_repo.get_by_id(schema.PER_Persona)
        if not persona:
            raise HTTPException(404, "PERSONA_NOT_FOUND")
        if schema.USU_Password:
            from types import SimpleNamespace
            from app.services.password_history import validate_new_password
            validate_new_password(
                SimpleNamespace(USU_Username=schema.USU_Username, persona=persona), schema.USU_Password,
            )

        if await self.usu_repo.get_by_username(schema.USU_Username):
            raise HTTPException(400, "USERNAME_ALREADY_EXISTS")

        # Una persona = un usuario (UNIQUE en BD, validamos antes para mejor error)
        if await self.per_repo.has_usuario(schema.PER_Persona):
            raise HTTPException(400, "PERSON_ALREADY_HAS_USER")

        obj = await self.usu_repo.create(schema)
        # La contraseña la eligió el administrador: es temporal y el titular
        # debe cambiarla en su primer inicio de sesión.
        if schema.USU_Password:
            obj.USU_Debe_Cambiar_Password = True
        await self._apply_scope(
            obj, rol=schema.USU_Rol, global_=schema.USU_Alcance_Global, sede_ids=schema.sedes,
            requester_role=requester_role,
        )
        await self._commit_audit(
            accion="CREATE", entidad="INV_USUARIO",
            snapshot={
                "username": schema.USU_Username,
                "rol": schema.USU_Rol,
                "sso_habilitado": schema.USU_SSO_Habilitado,
                "sso_provider": schema.USU_SSO_Provider,
                "password_interna": bool(schema.USU_Password),
                "alcance": {
                    "global": obj.alcance_global_efectivo,
                    "sedes": sorted(s.SED_Sede for s in (obj.sedes or [])),
                },
            },
            usuario_id=usuario_id, ip=ip,
        )
        return await self.usu_repo.get_by_id(obj.USU_Usuario)

    async def update_usuario(
        self, usuario_id_target: uuid.UUID, schema: UsuarioUpdate,
        requester_role: str, usuario_id=None, ip=None,
    ):
        target = await self.get_usuario(usuario_id_target)
        # La cuenta propia se gestiona por autoservicio (/me): un administrador
        # no puede cambiarse el rol, desactivarse ni fijarse la contraseña aquí.
        if usuario_id is not None and target.USU_Usuario == usuario_id:
            raise HTTPException(403, "CANNOT_MODIFY_OWN_ACCOUNT")

        # Capturamos el estado ANTES de mutar, para la traza forense antes→después.
        rol_anterior = target.USU_Rol
        estado_anterior = target.USU_Estado
        sso_habilitado_anterior = target.USU_SSO_Habilitado
        sso_provider_anterior = target.USU_SSO_Provider

        # Protección de jerarquía (ver app/core/roles.py)
        if target.USU_Rol == "SUPER_ADMIN" and requester_role != "SUPER_ADMIN":
            raise HTTPException(403, "CANNOT_MODIFY_SUPER_ADMIN")
        if not roles.can_manage(requester_role, target.USU_Rol):
            raise HTTPException(403, "INSUFFICIENT_PERMISSIONS")
        # ANTI-ESCALADA: los roles protegidos (SUPER_ADMIN, ADMIN_SEGURIDAD) solo
        # los otorga un SUPER_ADMIN. Sin esto, un administrador podía elevar a un
        # usuario de bajo privilegio y fabricarse un par o un superior.
        if schema.USU_Rol and not roles.can_grant(requester_role, schema.USU_Rol):
            raise HTTPException(403, "ONLY_SUPER_ADMIN_CAN_GRANT_ADMIN_ROLES")

        # Protección del último super-admin
        will_disable = schema.USU_Estado is False
        will_demote = bool(schema.USU_Rol) and schema.USU_Rol != "SUPER_ADMIN"
        if target.USU_Rol == "SUPER_ADMIN" and (will_disable or will_demote):
            count = await self.usu_repo.count_active_super_admins()
            if count <= 1:
                raise HTTPException(400, "CANNOT_DISABLE_LAST_SUPER_ADMIN")

        # Política de contraseña si viene cambio
        if schema.USU_Password:
            from app.services.password_history import (
                ensure_not_reused, remember_current, validate_new_password,
            )
            validate_new_password(target, schema.USU_Password)
            await ensure_not_reused(self.db, target, schema.USU_Password)
            await remember_current(self.db, target)
            # Revocar todos los tokens emitidos al usuario (deja de aceptar los viejos)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            # Expira muy tarde: 30 días — suficiente para cubrir refresh
            await self.gov_repo.revoke_all_user_tokens(usuario_id_target, expira=now.replace(year=now.year + 1))

        sso_enabled_next = (
            schema.USU_SSO_Habilitado
            if schema.USU_SSO_Habilitado is not None
            else target.USU_SSO_Habilitado
        )
        has_internal_password_next = bool(target.USU_Password_Hash or schema.USU_Password)
        if schema.USU_SSO_Provider and not sso_enabled_next:
            raise HTTPException(400, "SSO_PROVIDER_REQUIRES_SSO_ENABLED")
        if not sso_enabled_next and not has_internal_password_next:
            raise HTTPException(400, "PASSWORD_REQUIRED_WHEN_SSO_DISABLED")

        scope_fields = {"USU_Alcance_Global", "sedes"}
        obj = await self.usu_repo.update(
            usuario_id_target, schema, exclude=scope_fields,
        )
        if schema.USU_Password:
            # Fijada por un administrador → temporal (cambio obligatorio).
            obj.USU_Debe_Cambiar_Password = True
        alcance_diff = await self._apply_scope(
            obj,
            rol=obj.USU_Rol,
            global_=schema.USU_Alcance_Global,
            sede_ids=schema.sedes,
            requester_role=requester_role,
        )

        cambios = schema.model_dump(exclude_unset=True, exclude={"USU_Password"})
        # Diff explícito antes→después solo para los campos sensibles que cambian
        # de valor. Permite responder "¿quién cambió de qué rol a qué rol?" desde
        # una sola fila de la bitácora (auditoría append-only).
        diff: dict = {}
        if schema.USU_Rol is not None and schema.USU_Rol != rol_anterior:
            diff["USU_Rol"] = {"antes": rol_anterior, "despues": schema.USU_Rol}
        if schema.USU_Estado is not None and schema.USU_Estado != estado_anterior:
            diff["USU_Estado"] = {"antes": estado_anterior, "despues": schema.USU_Estado}
        if schema.USU_SSO_Habilitado is not None and schema.USU_SSO_Habilitado != sso_habilitado_anterior:
            diff["USU_SSO_Habilitado"] = {
                "antes": sso_habilitado_anterior,
                "despues": schema.USU_SSO_Habilitado,
            }
        if schema.USU_SSO_Provider is not None and schema.USU_SSO_Provider != sso_provider_anterior:
            diff["USU_SSO_Provider"] = {
                "antes": sso_provider_anterior,
                "despues": schema.USU_SSO_Provider,
            }
        if alcance_diff:
            diff["alcance"] = alcance_diff

        await self._commit_audit(
            accion="UPDATE", entidad="INV_USUARIO",
            snapshot={
                "target_id": str(usuario_id_target),
                "target_username": target.USU_Username,
                "cambios": cambios,
                "diff": diff,
                "password_cambiada": bool(schema.USU_Password),
            },
            usuario_id=usuario_id, ip=ip,
        )
        obj = await self.usu_repo.get_by_id(usuario_id_target)

        # Si un admin cambió la contraseña de otro usuario, avisar al DUEÑO
        # de la cuenta (post-commit, fire-and-forget).
        if schema.USU_Password:
            try:
                from app.core.email import notify_password_changed
                per = target.persona
                await notify_password_changed(
                    persona_nombre=(f"{per.PER_Primer_Nombre} {per.PER_Primer_Apellido}" if per else target.USU_Username),
                    username=target.USU_Username,
                    to_email=(per.PER_Email_Corporativo if per else None),
                    metodo="Cambio por administrador",
                    ip=ip,
                )
            except Exception:  # noqa: BLE001
                pass
        return obj

    async def reset_2fa(
        self, usuario_id_target: uuid.UUID, requester_role: str = "SUPER_ADMIN", usuario_id=None, ip=None,
    ):
        """
        Reset administrativo del 2FA de un usuario (acción de SUPER_ADMIN).
        Limpia método/secret, códigos de recuperación y OTPs de email pendientes.
        NO requiere la contraseña del objetivo (es una acción administrativa, p.ej.
        cuando el empleado pierde su teléfono). Si el rol del objetivo exige 2FA,
        será forzado a re-enrolar en su próximo login.
        """
        target = await self._manageable_target(usuario_id_target, requester_role, usuario_id)
        estaba_habilitado = bool(target.USU_2FA_Habilitado)
        target.USU_2FA_Habilitado = False
        target.USU_2FA_Metodo = None
        target.USU_2FA_Secret = None
        await self.gov_repo.delete_recovery_codes(usuario_id_target)
        await self.gov_repo.invalidate_email_otps(usuario_id_target)
        # Sin segundo factor, las sesiones abiertas no deben seguir vivas.
        await self.gov_repo.revoke_all_user_tokens(usuario_id_target, expira=_far_future())
        await self._commit_audit(
            accion="2FA_RESET_BY_ADMIN", entidad="INV_USUARIO",
            snapshot={
                "target_id": str(usuario_id_target),
                "target_username": target.USU_Username,
                "estaba_habilitado": estaba_habilitado,
            },
            usuario_id=usuario_id, ip=ip,
        )
        return target

    async def _manageable_target(self, target_id: uuid.UUID, requester_role: str, requester_id):
        """Cuenta objetivo de una acción administrativa, validando la jerarquía."""
        target = await self.get_usuario(target_id)
        if requester_id is not None and target.USU_Usuario == requester_id:
            raise HTTPException(403, "CANNOT_MODIFY_OWN_ACCOUNT")
        if not roles.can_manage(requester_role, target.USU_Rol):
            raise HTTPException(403, "INSUFFICIENT_PERMISSIONS")
        return target

    async def reset_password(
        self, usuario_id_target: uuid.UUID, requester_role: str, usuario_id=None, ip=None,
    ) -> str:
        """
        Asigna una contraseña TEMPORAL aleatoria (se muestra una sola vez al
        administrador), obliga a cambiarla en el próximo inicio de sesión,
        desbloquea la cuenta y cierra todas sus sesiones. El administrador nunca
        conoce la contraseña definitiva del titular.
        """
        target = await self._manageable_target(usuario_id_target, requester_role, usuario_id)
        if target.USU_SSO_Habilitado and not target.USU_Password_Hash:
            raise HTTPException(400, "SSO_ONLY_ACCOUNT")
        temporal = generate_temporary_password(target.USU_Username)
        from app.services.password_history import remember_current
        await remember_current(self.db, target)
        target.USU_Password_Hash = get_password_hash(temporal)
        target.USU_Password_Cambiada_En = datetime.now(timezone.utc).replace(tzinfo=None)
        target.USU_Debe_Cambiar_Password = True
        target.USU_Intentos_Fallidos = 0
        target.USU_Bloqueado_Hasta = None
        await self.gov_repo.revoke_all_user_tokens(usuario_id_target, expira=_far_future())
        await self._commit_audit(
            accion="PASSWORD_RESET_BY_ADMIN", entidad="INV_USUARIO",
            snapshot={"target_id": str(usuario_id_target), "target_username": target.USU_Username},
            usuario_id=usuario_id, ip=ip,
        )
        try:
            from app.core.email import notify_password_changed
            per = target.persona
            await notify_password_changed(
                persona_nombre=(f"{per.PER_Primer_Nombre} {per.PER_Primer_Apellido}" if per else target.USU_Username),
                username=target.USU_Username,
                to_email=per.PER_Email_Corporativo if per else None,
                metodo="admin", ip=ip,
            )
        except Exception:  # noqa: BLE001 — el aviso es best-effort
            pass
        return temporal

    async def unlock_usuario(
        self, usuario_id_target: uuid.UUID, requester_role: str, usuario_id=None, ip=None,
    ):
        target = await self._manageable_target(usuario_id_target, requester_role, usuario_id)
        estaba_bloqueado = bool(target.USU_Bloqueado_Hasta)
        target.USU_Intentos_Fallidos = 0
        target.USU_Bloqueado_Hasta = None
        await self._commit_audit(
            accion="ACCOUNT_UNLOCKED_BY_ADMIN", entidad="INV_USUARIO",
            snapshot={"target_id": str(usuario_id_target), "target_username": target.USU_Username,
                      "estaba_bloqueado": estaba_bloqueado},
            usuario_id=usuario_id, ip=ip,
        )
        return target

    async def revoke_sessions(
        self, usuario_id_target: uuid.UUID, requester_role: str, usuario_id=None, ip=None,
    ):
        target = await self._manageable_target(usuario_id_target, requester_role, usuario_id)
        await self.gov_repo.revoke_all_user_tokens(usuario_id_target, expira=_far_future())
        await self._commit_audit(
            accion="SESSIONS_REVOKED_BY_ADMIN", entidad="INV_USUARIO",
            snapshot={"target_id": str(usuario_id_target), "target_username": target.USU_Username},
            usuario_id=usuario_id, ip=ip,
        )
        return target

    # =====================================================================
    # SESIONES ACTIVAS (administración)
    # =====================================================================
    async def list_user_sessions(self, usuario_id_target: uuid.UUID, requester_role: str, requester_id=None):
        from app.services import sessions
        target = await self.get_usuario(usuario_id_target)
        if requester_id is None or target.USU_Usuario != requester_id:
            if not roles.can_manage(requester_role, target.USU_Rol):
                raise HTTPException(403, "INSUFFICIENT_PERMISSIONS")
        return [sessions.serialize(s) for s in await sessions.list_sessions(self.db, usuario_id_target)]

    async def close_user_session(
        self, usuario_id_target: uuid.UUID, session_id: str, requester_role: str, usuario_id=None, ip=None,
    ) -> None:
        from app.services import sessions
        target = await self._manageable_target(usuario_id_target, requester_role, usuario_id)
        sesion = await sessions.get_session(self.db, session_id)
        if sesion is None or sesion.USU_Usuario != target.USU_Usuario:
            raise HTTPException(404, "SESSION_NOT_FOUND")
        if await sessions.close_session(self.db, sesion, "cerrada_por_administrador"):
            await self._commit_audit(
                accion="SESSION_CLOSED", entidad="SYS_SESION",
                snapshot={"target_id": str(target.USU_Usuario), "target_username": target.USU_Username,
                          "sesion": session_id, "dispositivo": sesion.SES_Dispositivo, "por": "administrador"},
                usuario_id=usuario_id, ip=ip,
            )

    async def all_active_sessions(self, requester_role: str) -> list[dict]:
        """Todas las sesiones activas con su titular (panel de seguridad)."""
        from app.services import sessions
        usuarios = {u.USU_Usuario: u for u in await self.usu_repo.get_all()}
        out = []
        for s in await sessions.list_sessions(self.db):
            u = usuarios.get(s.USU_Usuario)
            if u is None:
                continue
            per = u.persona
            out.append({
                **sessions.serialize(s),
                "username": u.USU_Username,
                "rol": u.USU_Rol,
                "nombre": f"{per.PER_Primer_Nombre} {per.PER_Primer_Apellido}" if per else u.USU_Username,
                "gestionable": roles.can_manage(requester_role, u.USU_Rol),
            })
        return out

    async def security_summary(self) -> dict:
        """Indicadores del panel de seguridad y la política vigente."""
        from app.core.config import settings
        from app.core.data_scope import db_rls_available, user_is_global
        from app.services import sessions
        from app.services.twofactor import role_requires_2fa
        usuarios = await self.usu_repo.get_all()
        activos = [u for u in usuarios if u.USU_Estado]
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        con_mfa = [u for u in activos if u.USU_2FA_Habilitado]
        sesiones_activas = await sessions.list_sessions(self.db)
        return {
            "sesiones_activas": len(sesiones_activas),
            "usuarios_alcance_global": sum(
                1 for u in activos if u.USU_Rol in roles.SCOPED_ROLES and user_is_global(u)
            ),
            # Cuentas de inventario sin sedes ni alcance global: no ven datos.
            "usuarios_sin_alcance": sum(
                1 for u in activos
                if u.USU_Rol in roles.SCOPED_ROLES and not user_is_global(u) and not u.sedes
            ),
            "rls_base_datos": db_rls_available() is True,
            "usuarios_activos": len(activos),
            "usuarios_inactivos": len(usuarios) - len(activos),
            "con_mfa": len(con_mfa),
            "cobertura_mfa": round(100 * len(con_mfa) / len(activos)) if activos else 0,
            "mfa_pendiente_obligatorio": sum(
                1 for u in activos
                if role_requires_2fa(u.USU_Rol) and not u.USU_2FA_Habilitado and not u.USU_SSO_Habilitado
            ),
            "bloqueados": sum(1 for u in activos if u.USU_Bloqueado_Hasta and u.USU_Bloqueado_Hasta > now),
            "cambio_password_pendiente": sum(1 for u in activos if u.USU_Debe_Cambiar_Password),
            "politica": {
                "mfa_roles_obligatorios": sorted(
                    r.strip() for r in (settings.TWO_FACTOR_REQUIRED_ROLES or "").split(",") if r.strip()
                ),
                "password_longitud_minima": settings.PASSWORD_MIN_LENGTH,
                "password_mayuscula": settings.PASSWORD_REQUIRE_UPPER,
                "password_minuscula": settings.PASSWORD_REQUIRE_LOWER,
                "password_digito": settings.PASSWORD_REQUIRE_DIGIT,
                "password_simbolo": settings.PASSWORD_REQUIRE_SYMBOL,
                "bloqueo_intentos": settings.ACCOUNT_LOCKOUT_THRESHOLD,
                "bloqueo_minutos": settings.ACCOUNT_LOCKOUT_MINUTES,
                "sesion_inactividad_minutos": settings.SESSION_IDLE_TIMEOUT_MINUTES,
                "sesion_maxima_horas": settings.SESSION_ABSOLUTE_MAX_HOURS,
                "password_historial": settings.PASSWORD_HISTORY_COUNT,
                "password_bloquea_comunes": True,
                "aviso_dispositivo_nuevo": settings.NEW_DEVICE_ALERT_ENABLED,
                "cuentas_inactivas_dias": settings.ACCOUNT_INACTIVITY_DISABLE_DAYS,
                "auditoria_retencion_dias": settings.AUDIT_RETENTION_DAYS,
            },
        }

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
