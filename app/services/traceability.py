"""Servicio de Trazabilidad: movimientos / asignaciones / transferencias."""
from __future__ import annotations

from app.core.errors import internal_error, InvalidStateTransitionError
from app.core.email import send_notification
from app.core.transactional import schedule_post_commit, transactional

import unicodedata
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalogs import EstadoOperativo
from app.models.location import Area
from app.models.organization import Persona, Usuario
from app.models.traceability import TipoMovimiento
from app.models.enums import EstadoOperativoEnum, TipoMovimientoEnum
from app.services.state_machine import AssetStateMachine
from app.repositories.core import CoreRepository
from app.repositories.governance import GovernanceRepository
from app.repositories.software import SoftwareRepository
from app.repositories.traceability import TraceabilityRepository
from app.services.base import BaseService
from app.schemas.traceability import (
    DevolucionCreate,
    MovimientoCreate,
    TipoMovimientoCreate,
    TipoMovimientoUpdate,
    TransferenciaCreate,
)


class TraceabilityService(BaseService[TraceabilityRepository]):
    repo_class = TraceabilityRepository

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.gov_repo = GovernanceRepository(db)
        self.core_repo = CoreRepository(db)

    def _schedule_notification(self, template: str, context: dict, **kwargs) -> None:
        schedule_post_commit(
            self,
            lambda: send_notification(template, context, **kwargs),
        )

    # =====================================================================
    # TIPO MOVIMIENTO
    # =====================================================================
    @transactional
    async def create_tipo_movimiento(self, schema: TipoMovimientoCreate, usuario_id=None, ip=None):
        existing = await self.db.execute(
            select(TipoMovimiento).where(TipoMovimiento.TMO_Nombre.ilike(schema.TMO_Nombre))
        )
        if existing.scalar_one_or_none():
            raise HTTPException(400, detail="MOVEMENT_TYPE_ALREADY_EXISTS")
        obj = await self.repo.create_tipo_movimiento(schema)
        await self.gov_repo.create_audit_log(
            "CREATE", "INV_TIPO_MOVIMIENTO",
            {"nombre": schema.TMO_Nombre},
            usuario_id=usuario_id, ip_origen=ip,
        )
        return obj

    async def list_tipos_movimiento(self):
        return await self.repo.get_tipos_movimiento()

    @transactional
    async def update_tipo_movimiento(self, id: int, schema: TipoMovimientoUpdate, usuario_id=None, ip=None):
        tipo = await self.repo.get_tipo_by_id(id)
        if not tipo:
            raise HTTPException(404, detail="MOVEMENT_TYPE_NOT_FOUND")
        obj = await self.repo.update_tipo(id, schema)
        await self.gov_repo.create_audit_log(
            "UPDATE", "INV_TIPO_MOVIMIENTO",
            {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip_origen=ip,
        )
        return obj

    @transactional
    async def delete_tipo_movimiento(self, id: int, usuario_id=None, ip=None):
        tipo = await self.repo.get_tipo_by_id(id)
        if not tipo:
            raise HTTPException(404, detail="MOVEMENT_TYPE_NOT_FOUND")
        count = await self.repo.count_movimientos_by_tipo(id)
        if count > 0:
            raise HTTPException(409, detail="CANNOT_DELETE_TYPE_HAS_MOVEMENTS")
        await self.repo.delete_tipo(id)
        await self.gov_repo.create_audit_log(
            "DELETE", "INV_TIPO_MOVIMIENTO",
            {"id": id, "nombre": tipo.TMO_Nombre},
            usuario_id=usuario_id, ip_origen=ip,
        )

    # =====================================================================
    # MOVIMIENTOS — ACID
    # =====================================================================
    async def list_movimientos(self, skip: int = 0, limit: int = 50):
        return await self.repo.get_all_movimientos(skip, limit)

    async def _operator_info(self, usuario_id: uuid.UUID | None) -> tuple[str, str, str | None]:
        """
        Dado el usuario_id que ejecuta una acción, retorna (nombre_completo,
        rol, email_corporativo). Si no se puede resolver, devuelve defaults
        seguros para mostrar "Sistema" en el template.
        """
        if not usuario_id:
            return ("Sistema", "", None)
        # Una sola consulta con JOIN (antes eran 2 selects secuenciales).
        row = (await self.db.execute(
            select(
                Usuario.USU_Username, Usuario.USU_Rol,
                Persona.PER_Primer_Nombre, Persona.PER_Primer_Apellido,
                Persona.PER_Email_Corporativo,
            )
            .join(Persona, Persona.PER_Persona == Usuario.PER_Persona, isouter=True)
            .where(Usuario.USU_Usuario == usuario_id)
        )).first()
        if not row:
            return ("Sistema", "", None)
        username, rol, nombre, apellido, email = row
        if nombre:
            return (f"{nombre} {apellido}", rol or "", email)
        return (username, rol or "", None)

    async def _get_estado_id(self, estado: EstadoOperativoEnum) -> int | None:
        """Resuelve el id de un EstadoOperativo por su valor Enum."""
        row = (await self.db.execute(
            select(EstadoOperativo).where(EstadoOperativo.EOP_Nombre.ilike(estado.value))
        )).scalar_one_or_none()
        return row.EOP_Estado_Operativo if row else None

    async def _get_estado_nombre_enum(self, estado_id: int | None) -> EstadoOperativoEnum | None:
        if estado_id is None:
            return None
        nombre = (await self.db.execute(
            select(EstadoOperativo.EOP_Nombre)
            .where(EstadoOperativo.EOP_Estado_Operativo == estado_id)
        )).scalar_one_or_none()
        if not nombre:
            return None
        try:
            return EstadoOperativoEnum(nombre)
        except ValueError:
            # Fallback para nombres legacy o no normalizados
            norm = self._normalize_catalog_name(nombre)
            for e in EstadoOperativoEnum:
                if self._normalize_catalog_name(e.value) in norm:
                    return e
            return None

    async def _get_tipo_movimiento_enum(self, tipo_id: int) -> TipoMovimientoEnum | None:
        """Devuelve el Enum del tipo de movimiento."""
        nombre = (await self.db.execute(
            select(TipoMovimiento.TMO_Nombre).where(TipoMovimiento.TMO_Tipo_Movimiento == tipo_id)
        )).scalar_one_or_none()
        if not nombre:
            return None
        try:
            return TipoMovimientoEnum(nombre)
        except ValueError:
            norm = self._normalize_catalog_name(nombre)
            for e in TipoMovimientoEnum:
                if self._normalize_catalog_name(e.value) in norm:
                    return e
            return None

    @staticmethod
    def _normalize_catalog_name(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()

    async def _set_activo_estado(self, activo_id: uuid.UUID, estado_id: int) -> None:
        """UPDATE puntual del EOP_Estado_Operativo de un activo."""
        from sqlalchemy import update as sql_update
        from app.models.core import Activo as ActivoModel
        await self.db.execute(
            sql_update(ActivoModel)
            .where(ActivoModel.ACT_Activo == activo_id)
            .values(EOP_Estado_Operativo=estado_id)
        )

    async def _sede_de_destino(self, area_id: int) -> int | None:
        """Sede del área de destino, validada contra el alcance del usuario."""
        from app.core.data_scope import area_sede_id, require_sede
        sede = await area_sede_id(self.db, area_id)
        if sede is None:
            raise HTTPException(400, detail="AREA_WITHOUT_SEDE")
        return require_sede(sede)

    async def _ubicar_en_sede(
        self, activo, persona, sede_id: int | None, *, usuario_id=None, ip: str | None = None,
    ) -> None:
        """
        La sede del activo sigue al área de su último movimiento. Si la persona
        aún no tiene sede, se completa con la del área donde recibe el equipo.
        Un cambio de sede se audita en la sede de ORIGEN (el evento principal va
        a la de destino): así el auditor de cada sede ve el activo salir o entrar.
        """
        from sqlalchemy import update as _upd
        from app.models.core import Activo as _Act
        if sede_id is None:
            return
        if activo.SED_Sede is not None and activo.SED_Sede != sede_id:
            await self.gov_repo.create_audit_log(
                "ASSET_SEDE_CHANGE", "INV_ACTIVO",
                {"activo": str(activo.ACT_Activo), "codigo": activo.ACT_Codigo_Interno,
                 "sede_origen": activo.SED_Sede, "sede_destino": sede_id},
                usuario_id=usuario_id, ip_origen=ip, sede_id=activo.SED_Sede,
            )
        if activo.SED_Sede != sede_id:
            await self.db.execute(
                _upd(_Act).where(_Act.ACT_Activo == activo.ACT_Activo).values(SED_Sede=sede_id)
                .execution_options(synchronize_session="fetch")
            )
        if persona is not None and persona.SED_Sede is None:
            await self.db.execute(
                _upd(Persona)
                .where(Persona.PER_Persona == persona.PER_Persona, Persona.SED_Sede.is_(None))
                .values(SED_Sede=sede_id)
                .execution_options(synchronize_session="fetch")
            )

    @transactional
    async def registrar_movimiento(
        self,
        schema: MovimientoCreate,
        usuario_id: uuid.UUID | None = None,
        ip: str | None = None,
    ):
        """
        Asigna activo a persona/área. Lock + UPDATE condicional aseguran
        que no queden dos movimientos abiertos para el mismo activo.
        """
        try:
            activo = await self.core_repo.get_by_id_simple(schema.ACT_Activo)
            if not activo:
                raise HTTPException(404, detail="ASSET_NOT_FOUND")

            tipo_enum = await self._get_tipo_movimiento_enum(schema.TMO_Tipo_Movimiento)

            # Validar estado operacional antes de abrir custodia.
            estado_actual = await self._get_estado_nombre_enum(activo.EOP_Estado_Operativo)
            if not estado_actual:
                 raise HTTPException(500, detail="UNKNOWN_CURRENT_STATE")

            # Determinar estado objetivo según el tipo de movimiento.
            target_estado_enum: EstadoOperativoEnum | None = None
            if tipo_enum in (TipoMovimientoEnum.ASIGNACION, TipoMovimientoEnum.PRESTAMO, TipoMovimientoEnum.TRANSFERENCIA):
                target_estado_enum = EstadoOperativoEnum.ASIGNADO
            elif tipo_enum == TipoMovimientoEnum.DEVOLUCION:
                target_estado_enum = EstadoOperativoEnum.BODEGA
            elif tipo_enum == TipoMovimientoEnum.INGRESO:
                target_estado_enum = EstadoOperativoEnum.DISPONIBLE
            elif tipo_enum == TipoMovimientoEnum.BAJA:
                target_estado_enum = EstadoOperativoEnum.BAJA

            # VALIDACIÓN DE LA MÁQUINA DE ESTADOS
            if target_estado_enum:
                AssetStateMachine.validate_transition(estado_actual, target_estado_enum)

            # Persona y Área
            persona = (await self.db.execute(
                select(Persona).where(Persona.PER_Persona == schema.PER_Persona)
            )).scalar_one_or_none()
            if not persona:
                raise HTTPException(404, detail="PERSON_NOT_FOUND")

            area = (await self.db.execute(
                select(Area).where(Area.ARE_Area == schema.ARE_Area)
            )).scalar_one_or_none()
            if not area:
                raise HTTPException(404, detail="AREA_NOT_FOUND")
            # El área de destino debe estar en una sede del alcance.
            sede_destino = await self._sede_de_destino(area.ARE_Area)

            # Lock del movimiento vigente.
            vigente = await self.repo.get_movimiento_vigente(schema.ACT_Activo, lock=True)
            if tipo_enum in (TipoMovimientoEnum.ASIGNACION, TipoMovimientoEnum.PRESTAMO):
                if vigente:
                    raise HTTPException(409, detail="ASSET_ALREADY_ASSIGNED_USE_TRANSFER")
                if estado_actual not in (EstadoOperativoEnum.DISPONIBLE, EstadoOperativoEnum.BODEGA):
                    raise HTTPException(400, detail="ASSET_NOT_AVAILABLE_FOR_ASSIGNMENT")

            await self._ubicar_en_sede(activo, persona, sede_destino, usuario_id=usuario_id, ip=ip)
            nuevo = await self.repo.create_movimiento(schema)

            # Aplicar transición de estado
            if target_estado_enum:
                nuevo_estado_id = await self._get_estado_id(target_estado_enum)
                if nuevo_estado_id is None:
                    raise HTTPException(
                        500, detail="SYSTEM_CONFIG_ERROR_MISSING_OPERATIONAL_STATE"
                    )
                if nuevo_estado_id != activo.EOP_Estado_Operativo:
                    await self._set_activo_estado(schema.ACT_Activo, nuevo_estado_id)

            # Cambio OPCIONAL de hostname
            if schema.ACT_Hostname is not None and \
                    (schema.ACT_Hostname or None) != (activo.ACT_Hostname or None):
                from sqlalchemy import update as _upd
                from app.models.core import Activo as _Act
                await self.db.execute(
                    _upd(_Act).where(_Act.ACT_Activo == schema.ACT_Activo)
                    .values(ACT_Hostname=schema.ACT_Hostname or None)
                )

            await self.gov_repo.create_audit_log(
                "ASSIGN", "INV_MOVIMIENTO",
                {
                    "activo": str(schema.ACT_Activo),
                    "persona": str(schema.PER_Persona),
                    "area": schema.ARE_Area,
                    "sede": sede_destino,
                    "tipo": tipo_enum.value if tipo_enum else None,
                },
                usuario_id=usuario_id, ip_origen=ip, sede_id=sede_destino,
            )

            resultado = await self.repo.get_by_id_full(nuevo.MOV_Movimiento)

            try:
                a = resultado.activo
                p = resultado.persona
                template = "asignacion"
                marca = ""
                modelo = ""
                tipo_act = ""
                if a and getattr(a, "modelo", None):
                    modelo = a.modelo.MOD_Nombre or ""
                    if getattr(a.modelo, "marca", None):
                        marca = a.modelo.marca.MAR_Nombre or ""
                if a and getattr(a, "tipo_activo", None):
                    tipo_act = a.tipo_activo.TAC_Nombre or ""
                op_name, op_role, op_email = await self._operator_info(usuario_id)
                self._schedule_notification(
                    template,
                    {
                        "codigo": a.ACT_Codigo_Interno if a else "",
                        "serie": a.ACT_Serie_Fabricante if a else "",
                        "hostname": a.ACT_Hostname if a else "",
                        "tipo": tipo_act,
                        "marca": marca,
                        "modelo": modelo,
                        "persona_nombre": f"{p.PER_Primer_Nombre} {p.PER_Primer_Apellido}" if p else "",
                        "fecha": resultado.MOV_Fecha_Asignacion.isoformat() if resultado.MOV_Fecha_Asignacion else "",
                        "area": resultado.area.ARE_Nombre if resultado.area else "",
                        "observacion": resultado.MOV_Observacion or "",
                    },
                    to=[p.PER_Email_Corporativo] if p and p.PER_Email_Corporativo else (),
                    reply_to=op_email,
                    operator_name=op_name,
                    operator_role=op_role,
                )
            except Exception as e:  # noqa: BLE001
                import structlog
                structlog.get_logger("traceability").warning(
                    "notify.assign_failed", error=str(e)[:200],
                )

            return resultado
        except HTTPException:
            raise
        except InvalidStateTransitionError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": exc.code,
                    "current_state": exc.current_state,
                    "target_state": exc.target_state,
                    "message": exc.message,
                },
            ) from exc
        except IntegrityError:
            raise HTTPException(409, "ASSET_ALREADY_HAS_OPEN_MOVEMENT")
        except Exception as e:
            raise internal_error(e, "TRANSACTION_FAILED")

    async def asignaciones_vigentes_persona(self, persona_id: uuid.UUID):
        """Lista los activos actualmente bajo custodia de una persona."""
        persona = (await self.db.execute(
            select(Persona).where(Persona.PER_Persona == persona_id)
        )).scalar_one_or_none()
        if not persona:
            raise HTTPException(404, "PERSON_NOT_FOUND")
        return await self.repo.get_asignaciones_vigentes_persona(persona_id)

    @transactional
    async def offboarding_persona(
        self,
        persona_id: uuid.UUID,
        desactivar_usuario: bool = True,
        usuario_id: uuid.UUID | None = None,
        ip: str | None = None,
    ):
        """
        OFFBOARDING ATÓMICO + IDEMPOTENTE
        """
        try:
            persona = (await self.db.execute(
                select(Persona).where(Persona.PER_Persona == persona_id)
            )).scalar_one_or_none()
            if not persona:
                raise HTTPException(404, "PERSON_NOT_FOUND")
            from app.core.data_scope import elevated, require_owned
            require_owned(persona.SED_Sede)
            # El offboarding cierra TODAS las custodias: si alguna está en una
            # sede fuera del alcance, se haría a medias. Lo resuelve alguien con
            # alcance sobre todas esas sedes.
            visibles = len(await self.repo.get_asignaciones_vigentes_persona(persona_id))
            async with elevated(self.db):
                totales = len(await self.repo.get_asignaciones_vigentes_persona(persona_id))
            if totales != visibles:
                raise HTTPException(403, "OFFBOARDING_REQUIRES_SCOPE_OVER_ALL_ASSETS")
            persona_estaba_activa = bool(persona.PER_Estado)

            # 1. Capturar lista de activos antes de cerrar
            vigentes = await self.repo.get_asignaciones_vigentes_persona(persona_id)
            activos_ids = [str(m.ACT_Activo) for m in vigentes]
            activos_uuid = [m.ACT_Activo for m in vigentes]

            # 2. Cerrar todos los movimientos
            cerrados = await self.repo.cerrar_todos_movimientos_persona(persona_id)

            # 3. Cambiar estado operativo a "En Bodega"
            estado_bodega_id = await self._get_estado_id(EstadoOperativoEnum.BODEGA)
            if activos_ids:
                if not estado_bodega_id:
                    raise HTTPException(
                        500, detail="SYSTEM_CONFIG_ERROR_MISSING_OPERATIONAL_STATE"
                    )
                from sqlalchemy import update as sql_update
                from app.models.core import Activo
                await self.db.execute(
                    sql_update(Activo)
                    .where(Activo.ACT_Activo.in_([m.ACT_Activo for m in vigentes]))
                    .values(EOP_Estado_Operativo=estado_bodega_id)
                )

            # 4. Liberar licencias
            licencias_liberadas = await SoftwareRepository(self.db).liberar_instalaciones_por_destino(
                activos_ids=activos_uuid,
                persona_id=persona_id,
            )

            # 5. Desactivar usuario
            usuario_desactivado = False
            if desactivar_usuario:
                usuario_target = (await self.db.execute(
                    select(Usuario).where(Usuario.PER_Persona == persona_id)
                )).scalar_one_or_none()
                if usuario_target:
                    if usuario_target.USU_Rol == "SUPER_ADMIN":
                        from sqlalchemy import func as sql_func
                        count_sa = (await self.db.execute(
                            select(sql_func.count()).select_from(Usuario)
                            .where(Usuario.USU_Rol == "SUPER_ADMIN", Usuario.USU_Estado.is_(True))
                        )).scalar() or 0
                        if count_sa <= 1:
                            raise HTTPException(
                                400, "CANNOT_OFFBOARD_LAST_SUPER_ADMIN"
                            )
                    usuario_target.USU_Estado = False
                    from datetime import datetime as _dt, timezone as _tz
                    far = _dt.now(_tz.utc).replace(tzinfo=None).replace(year=_dt.now().year + 1)
                    await self.gov_repo.revoke_all_user_tokens(usuario_target.USU_Usuario, expira=far)
                    usuario_desactivado = True

            # 6. Marcar persona como inactiva
            persona.PER_Estado = False

            algo_cambio = (
                cerrados > 0
                or licencias_liberadas > 0
                or usuario_desactivado
                or persona_estaba_activa
            )

            if algo_cambio:
                await self.gov_repo.create_audit_log(
                    accion="OFFBOARDING",
                    entidad="INV_PERSONA",
                    snapshot={
                        "persona_id": str(persona_id),
                        "usuario_desactivado": usuario_desactivado,
                        "movimientos_cerrados": cerrados,
                        "activos_devueltos": len(activos_ids),
                        "activos_ids": activos_ids,
                        "licencias_liberadas": licencias_liberadas,
                    },
                    usuario_id=usuario_id,
                    ip_origen=ip,
                    sede_id=persona.SED_Sede,
                )

            if algo_cambio:
                try:
                    activos_codigos: list[str] = []
                    if vigentes:
                        from app.models.core import Activo as _Activo
                        rows = (await self.db.execute(
                            select(_Activo.ACT_Codigo_Interno)
                            .where(_Activo.ACT_Activo.in_([m.ACT_Activo for m in vigentes]))
                        )).all()
                        activos_codigos = [r[0] for r in rows]
                    op_name, op_role, op_email = await self._operator_info(usuario_id)
                    self._schedule_notification(
                        "offboarding",
                        {
                            "persona_nombre": f"{persona.PER_Primer_Nombre} {persona.PER_Primer_Apellido}",
                            "persona_email": persona.PER_Email_Corporativo or "—",
                            "num_activos": len(activos_codigos),
                            "activos_lista": activos_codigos,
                            "usuario_desactivado": "Sí" if usuario_desactivado else "No",
                            "fecha": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                        },
                        to=(),
                        affected=[persona.PER_Email_Corporativo] if persona.PER_Email_Corporativo else (),
                        reply_to=op_email,
                        operator_name=op_name,
                        operator_role=op_role,
                    )
                except Exception:  # noqa: BLE001
                    pass

            return {
                "status": "success",
                "persona_id": str(persona_id),
                "movimientos_cerrados": cerrados,
                "activos_devueltos_a_bodega": len(activos_ids),
                "licencias_liberadas": licencias_liberadas,
                "usuario_desactivado": usuario_desactivado,
                "persona_inactivada": True,
                "idempotent_noop": not algo_cambio,
            }
        except HTTPException:
            raise
        except Exception as e:
            raise internal_error(e, "OFFBOARDING_FAILED")

    @transactional
    async def registrar_devolucion(
        self,
        schema: DevolucionCreate,
        usuario_id: uuid.UUID | None = None,
        ip: str | None = None,
    ):
        try:
            vigente = await self.repo.get_movimiento_vigente(schema.ACT_Activo, lock=True)
            if not vigente:
                raise HTTPException(400, detail="ASSET_IS_NOT_ASSIGNED")

            activo = await self.core_repo.get_by_id_simple(schema.ACT_Activo)
            estado_actual = await self._get_estado_nombre_enum(activo.EOP_Estado_Operativo)
            
            # Validar transición: Asignado -> Bodega
            AssetStateMachine.validate_transition(estado_actual, EstadoOperativoEnum.BODEGA)

            cerrado = await self.repo.cerrar_movimiento(vigente.MOV_Movimiento)
            if not cerrado:
                raise HTTPException(409, detail="MOVEMENT_ALREADY_CLOSED")

            estado_bodega_id = await self._get_estado_id(EstadoOperativoEnum.BODEGA)
            if estado_bodega_id is None:
                raise HTTPException(500, detail="SYSTEM_CONFIG_ERROR_MISSING_OPERATIONAL_STATE")
            await self._set_activo_estado(schema.ACT_Activo, estado_bodega_id)

            await self.gov_repo.create_audit_log(
                "RETURN", "INV_MOVIMIENTO",
                {"activo": str(schema.ACT_Activo), "estado_nuevo": estado_bodega_id},
                usuario_id=usuario_id, ip_origen=ip, sede_id=activo.SED_Sede if activo else None,
            )
            try:
                activo = await self.core_repo.get_by_id_simple(schema.ACT_Activo)
                persona = (await self.db.execute(
                    select(Persona).where(Persona.PER_Persona == vigente.PER_Persona)
                )).scalar_one_or_none()
                op_name, op_role, op_email = await self._operator_info(usuario_id)
                self._schedule_notification(
                    "devolucion",
                    {
                        "codigo": activo.ACT_Codigo_Interno if activo else "",
                        "persona_nombre": (
                            f"{persona.PER_Primer_Nombre} {persona.PER_Primer_Apellido}"
                            if persona else "—"
                        ),
                        "fecha": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                    },
                    to=[persona.PER_Email_Corporativo] if persona and persona.PER_Email_Corporativo else (),
                    reply_to=op_email,
                    operator_name=op_name,
                    operator_role=op_role,
                )
            except Exception:  # noqa: BLE001
                pass

            return {"status": "success", "message": "ASSET_RETURNED_SUCCESSFULLY"}
        except HTTPException:
            raise
        except InvalidStateTransitionError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": exc.code,
                    "current_state": exc.current_state,
                    "target_state": exc.target_state,
                    "message": exc.message,
                },
            ) from exc
        except Exception as e:
            raise internal_error(e, "TRANSACTION_FAILED")

    @transactional
    async def registrar_transferencia(
        self,
        schema: TransferenciaCreate,
        usuario_id: uuid.UUID | None = None,
        ip: str | None = None,
    ):
        try:
            activo = await self.core_repo.get_by_id_simple(schema.ACT_Activo)
            if not activo:
                raise HTTPException(404, detail="ASSET_NOT_FOUND")

            estado_actual = await self._get_estado_nombre_enum(activo.EOP_Estado_Operativo)
            
            # Validar transición: Actual -> Asignado (Transferencia)
            AssetStateMachine.validate_transition(estado_actual, EstadoOperativoEnum.ASIGNADO)

            vigente = await self.repo.get_movimiento_vigente(schema.ACT_Activo, lock=True)
            if not vigente:
                raise HTTPException(400, detail="ASSET_IS_NOT_ASSIGNED_CANNOT_TRANSFER")

            persona = (await self.db.execute(
                select(Persona).where(Persona.PER_Persona == schema.PER_Persona_Destino)
            )).scalar_one_or_none()
            if not persona:
                raise HTTPException(404, detail="DESTINATION_PERSON_NOT_FOUND")

            area = (await self.db.execute(
                select(Area).where(Area.ARE_Area == schema.ARE_Area_Destino)
            )).scalar_one_or_none()
            if not area:
                raise HTTPException(404, detail="DESTINATION_AREA_NOT_FOUND")
            sede_destino = await self._sede_de_destino(area.ARE_Area)

            tipo_asignacion_id = (await self.db.execute(
                select(TipoMovimiento.TMO_Tipo_Movimiento)
                .where(TipoMovimiento.TMO_Nombre.ilike(TipoMovimientoEnum.ASIGNACION.value))
            )).scalar_one_or_none()
            if not tipo_asignacion_id:
                # Fallback search if exact Enum value not found in DB yet
                tipo_asignacion_id = (await self.db.execute(
                    select(TipoMovimiento.TMO_Tipo_Movimiento)
                    .where(TipoMovimiento.TMO_Nombre.ilike("%Asignación%"))
                )).scalar_one_or_none()
                
            if not tipo_asignacion_id:
                raise HTTPException(500, detail="SYSTEM_CONFIG_ERROR_MISSING_ASSIGNMENT_TYPE")

            await self.repo.cerrar_movimiento(vigente.MOV_Movimiento)
            sede_origen = activo.SED_Sede
            await self._ubicar_en_sede(activo, persona, sede_destino, usuario_id=usuario_id, ip=ip)

            nuevo_mov = MovimientoCreate(
                ACT_Activo=schema.ACT_Activo,
                PER_Persona=schema.PER_Persona_Destino,
                ARE_Area=schema.ARE_Area_Destino,
                TMO_Tipo_Movimiento=tipo_asignacion_id,
                MOV_Observacion=schema.MOV_Observacion or "Transferencia de custodia",
            )
            created = await self.repo.create_movimiento(nuevo_mov)

            estado_asignado_id = await self._get_estado_id(EstadoOperativoEnum.ASIGNADO)
            if estado_asignado_id is None:
                raise HTTPException(500, detail="SYSTEM_CONFIG_ERROR_MISSING_OPERATIONAL_STATE")
            await self._set_activo_estado(schema.ACT_Activo, estado_asignado_id)

            await self.gov_repo.create_audit_log(
                "TRANSFER", "INV_MOVIMIENTO",
                {
                    "activo": str(schema.ACT_Activo),
                    "de": str(vigente.PER_Persona),
                    "a": str(schema.PER_Persona_Destino),
                    "sede_origen": sede_origen,
                    "sede_destino": sede_destino,
                },
                usuario_id=usuario_id, ip_origen=ip, sede_id=sede_destino,
            )
            try:
                origen = (await self.db.execute(
                    select(Persona).where(Persona.PER_Persona == vigente.PER_Persona)
                )).scalar_one_or_none()
                destino = (await self.db.execute(
                    select(Persona).where(Persona.PER_Persona == schema.PER_Persona_Destino)
                )).scalar_one_or_none()
                activo = await self.core_repo.get_by_id_simple(schema.ACT_Activo)
                emails_to = [
                    e for e in (
                        origen.PER_Email_Corporativo if origen else None,
                        destino.PER_Email_Corporativo if destino else None,
                    ) if e
                ]
                op_name, op_role, op_email = await self._operator_info(usuario_id)
                self._schedule_notification(
                    "transferencia",
                    {
                        "codigo": activo.ACT_Codigo_Interno if activo else "",
                        "origen_nombre": (
                            f"{origen.PER_Primer_Nombre} {origen.PER_Primer_Apellido}"
                            if origen else "—"
                        ),
                        "destino_nombre": (
                            f"{destino.PER_Primer_Nombre} {destino.PER_Primer_Apellido}"
                            if destino else "—"
                        ),
                        "fecha": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                    },
                    to=emails_to,
                    reply_to=op_email,
                    operator_name=op_name,
                    operator_role=op_role,
                )
            except Exception:  # noqa: BLE001
                pass
            return await self.repo.get_by_id_full(created.MOV_Movimiento)
        except HTTPException:
            raise
        except InvalidStateTransitionError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": exc.code,
                    "current_state": exc.current_state,
                    "target_state": exc.target_state,
                    "message": exc.message,
                },
            ) from exc
        except IntegrityError:
            raise HTTPException(409, "ASSET_ALREADY_HAS_OPEN_MOVEMENT")
        except Exception as e:
            raise internal_error(e, "TRANSACTION_FAILED")
