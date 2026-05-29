"""Servicio de Trazabilidad: movimientos / asignaciones / transferencias."""
from __future__ import annotations

from app.core.errors import internal_error
from app.core.email import send_notification

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalogs import EstadoOperativo
from app.models.location import Area
from app.models.organization import Persona, Usuario
from app.models.traceability import TipoMovimiento
from app.repositories.core import CoreRepository
from app.repositories.governance import GovernanceRepository
from app.repositories.traceability import TraceabilityRepository
from app.schemas.traceability import (
    DevolucionCreate,
    MovimientoCreate,
    TipoMovimientoCreate,
    TipoMovimientoUpdate,
    TransferenciaCreate,
)


class TraceabilityService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TraceabilityRepository(db)
        self.gov_repo = GovernanceRepository(db)
        self.core_repo = CoreRepository(db)

    # =====================================================================
    # TIPO MOVIMIENTO
    # =====================================================================
    async def create_tipo_movimiento(self, schema: TipoMovimientoCreate, usuario_id=None, ip=None):
        try:
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
            await self.db.commit()
            await self.db.refresh(obj)
            return obj
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def list_tipos_movimiento(self):
        return await self.repo.get_tipos_movimiento()

    async def update_tipo_movimiento(self, id: int, schema: TipoMovimientoUpdate, usuario_id=None, ip=None):
        try:
            tipo = await self.repo.get_tipo_by_id(id)
            if not tipo:
                raise HTTPException(404, detail="MOVEMENT_TYPE_NOT_FOUND")
            obj = await self.repo.update_tipo(id, schema)
            await self.gov_repo.create_audit_log(
                "UPDATE", "INV_TIPO_MOVIMIENTO",
                {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            return obj
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def delete_tipo_movimiento(self, id: int, usuario_id=None, ip=None):
        try:
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
            await self.db.commit()
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    # =====================================================================
    # MOVIMIENTOS — ACID
    # =====================================================================
    async def list_movimientos(self, skip: int = 0, limit: int = 50):
        return await self.repo.get_all_movimientos(skip, limit)

    async def _get_estado_id(self, nombre_ilike: str) -> int | None:
        """Resuelve el id de un EstadoOperativo por nombre (case-insensitive)."""
        row = (await self.db.execute(
            select(EstadoOperativo).where(EstadoOperativo.EOP_Nombre.ilike(nombre_ilike))
        )).scalar_one_or_none()
        return row.EOP_Estado_Operativo if row else None

    async def _get_tipo_movimiento_nombre(self, tipo_id: int) -> str:
        """Devuelve el nombre del tipo de movimiento (para decidir la transición)."""
        row = (await self.db.execute(
            select(TipoMovimiento).where(TipoMovimiento.TMO_Tipo_Movimiento == tipo_id)
        )).scalar_one_or_none()
        return (row.TMO_Nombre or "").lower() if row else ""

    async def _set_activo_estado(self, activo_id: uuid.UUID, estado_id: int) -> None:
        """UPDATE puntual del EOP_Estado_Operativo de un activo."""
        from sqlalchemy import update as sql_update
        from app.models.core import Activo as ActivoModel
        await self.db.execute(
            sql_update(ActivoModel)
            .where(ActivoModel.ACT_Activo == activo_id)
            .values(EOP_Estado_Operativo=estado_id)
        )

    async def registrar_movimiento(
        self,
        schema: MovimientoCreate,
        usuario_id: uuid.UUID | None = None,
        ip: str | None = None,
    ):
        """
        Asigna activo a persona/área. Lock + UPDATE condicional aseguran
        que no queden dos movimientos abiertos para el mismo activo.

        Transición de estado (atómica, en la MISMA transacción):
          - ASIGNACIÓN / PRÉSTAMO → estado "Asignado"
          - DEVOLUCIÓN           → estado "En Bodega"
          - INGRESO              → estado "Disponible"
        """
        try:
            activo = await self.core_repo.get_by_id_simple(schema.ACT_Activo)
            if not activo:
                raise HTTPException(404, detail="ASSET_NOT_FOUND")

            # Validar estado != Baja
            estado_baja_id = await self._get_estado_id("Baja")
            if estado_baja_id and activo.EOP_Estado_Operativo == estado_baja_id:
                raise HTTPException(400, detail="CANNOT_ASSIGN_DECOMMISSIONED_ASSET")

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

            # Lock + cierre del movimiento vigente, si existe
            vigente = await self.repo.get_movimiento_vigente(schema.ACT_Activo, lock=True)
            if vigente:
                await self.repo.cerrar_movimiento(vigente.MOV_Movimiento)

            nuevo = await self.repo.create_movimiento(schema)

            # Transición de estado según el tipo de movimiento.
            tipo_nombre = await self._get_tipo_movimiento_nombre(schema.TMO_Tipo_Movimiento)
            nuevo_estado_id: int | None = None
            if "asign" in tipo_nombre or "préstam" in tipo_nombre or "prestam" in tipo_nombre:
                nuevo_estado_id = await self._get_estado_id("Asignado")
            elif "devol" in tipo_nombre:
                nuevo_estado_id = await self._get_estado_id("%Bodega%")
            elif "ingres" in tipo_nombre:
                nuevo_estado_id = await self._get_estado_id("Disponible")
            elif "transfer" in tipo_nombre:
                nuevo_estado_id = await self._get_estado_id("Asignado")

            if nuevo_estado_id and nuevo_estado_id != activo.EOP_Estado_Operativo:
                await self._set_activo_estado(schema.ACT_Activo, nuevo_estado_id)

            await self.gov_repo.create_audit_log(
                "ASSIGN", "INV_MOVIMIENTO",
                {
                    "activo": str(schema.ACT_Activo),
                    "persona": str(schema.PER_Persona),
                    "area": schema.ARE_Area,
                    "estado_nuevo": nuevo_estado_id,
                },
                usuario_id=usuario_id, ip_origen=ip,
            )

            await self.db.commit()
            resultado = await self.repo.get_by_id_full(nuevo.MOV_Movimiento)

            # Notificación por email (best-effort, post-commit). Si falla SMTP,
            # NO revertimos: la operación de negocio ya está persistida.
            try:
                a = resultado.activo
                p = resultado.persona
                template = "asignacion" if "transfer" not in tipo_nombre else "asignacion"
                marca = ""
                modelo = ""
                tipo_act = ""
                if a and getattr(a, "modelo", None):
                    modelo = a.modelo.MOD_Nombre or ""
                    if getattr(a.modelo, "marca", None):
                        marca = a.modelo.marca.MAR_Nombre or ""
                if a and getattr(a, "tipo_activo", None):
                    tipo_act = a.tipo_activo.TAC_Nombre or ""
                await send_notification(
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
                )
            except Exception as e:  # noqa: BLE001
                # Logueamos pero no propagamos.
                import structlog
                structlog.get_logger("traceability").warning(
                    "notify.assign_failed", error=str(e)[:200],
                )

            return resultado
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def asignaciones_vigentes_persona(self, persona_id: uuid.UUID):
        """Lista los activos actualmente bajo custodia de una persona."""
        persona = (await self.db.execute(
            select(Persona).where(Persona.PER_Persona == persona_id)
        )).scalar_one_or_none()
        if not persona:
            raise HTTPException(404, "PERSON_NOT_FOUND")
        return await self.repo.get_asignaciones_vigentes_persona(persona_id)

    async def offboarding_persona(
        self,
        persona_id: uuid.UUID,
        desactivar_usuario: bool = True,
        usuario_id: uuid.UUID | None = None,
        ip: str | None = None,
    ):
        """
        OFFBOARDING ATÓMICO + IDEMPOTENTE:
        Llamarlo dos veces sobre la misma persona NO falla. Devuelve el estado
        actual (movimientos cerrados, usuario desactivado, persona inactiva).
        Solo aplica cambios y audita si quedan acciones por hacer.
        """
        try:
            persona = (await self.db.execute(
                select(Persona).where(Persona.PER_Persona == persona_id)
            )).scalar_one_or_none()
            if not persona:
                raise HTTPException(404, "PERSON_NOT_FOUND")

            # 1. Capturar lista de activos antes de cerrar (para snapshot)
            vigentes = await self.repo.get_asignaciones_vigentes_persona(persona_id)
            activos_ids = [str(m.ACT_Activo) for m in vigentes]

            # 2. Cerrar todos los movimientos en un solo UPDATE
            cerrados = await self.repo.cerrar_todos_movimientos_persona(persona_id)

            # 3. Cambiar estado operativo a "En Bodega" (si existe)
            estado_bodega = (await self.db.execute(
                select(EstadoOperativo).where(EstadoOperativo.EOP_Nombre.ilike("%Bodega%"))
            )).scalar_one_or_none()
            if estado_bodega and activos_ids:
                from sqlalchemy import update as sql_update
                from app.models.core import Activo
                await self.db.execute(
                    sql_update(Activo)
                    .where(Activo.ACT_Activo.in_([m.ACT_Activo for m in vigentes]))
                    .values(EOP_Estado_Operativo=estado_bodega.EOP_Estado_Operativo)
                )

            # 4. Desactivar usuario si aplica
            usuario_desactivado = False
            if desactivar_usuario:
                usuario_target = (await self.db.execute(
                    select(Usuario).where(Usuario.PER_Persona == persona_id)
                )).scalar_one_or_none()
                if usuario_target:
                    if usuario_target.USU_Rol == "SUPER_ADMIN":
                        # Proteger último super admin
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
                    # Revocar todos los tokens
                    from datetime import datetime as _dt, timezone as _tz
                    far = _dt.now(_tz.utc).replace(tzinfo=None).replace(year=_dt.now().year + 1)
                    await self.gov_repo.revoke_all_user_tokens(usuario_target.USU_Usuario, expira=far)
                    usuario_desactivado = True

            # 5. Marcar persona como inactiva
            persona.PER_Estado = False

            # 6. Idempotencia: solo auditamos si hubo cambios reales.
            #    Si la persona ya estaba inactiva, sin movimientos, sin usuario activo,
            #    no agregamos ruido en el audit log.
            algo_cambio = (
                cerrados > 0
                or usuario_desactivado
                or persona.PER_Estado is True  # antes era True, ahora False
            )

            if algo_cambio:
                await self.gov_repo.create_audit_log(
                    accion="OFFBOARDING",
                    entidad="INV_PERSONA",
                    snapshot={
                        "persona_id": str(persona_id),
                        "nombre": f"{persona.PER_Primer_Nombre} {persona.PER_Primer_Apellido}",
                        "email": persona.PER_Email_Corporativo,
                        "activos_devueltos": len(vigentes),
                        "activos_ids": activos_ids,
                        "usuario_desactivado": usuario_desactivado,
                        "movimientos_cerrados": cerrados,
                    },
                    usuario_id=usuario_id,
                    ip_origen=ip,
                )

            await self.db.commit()

            # Notificación post-commit
            if algo_cambio:
                try:
                    # Buscar códigos de activos liberados para listarlos en el email
                    activos_codigos: list[str] = []
                    if vigentes:
                        from app.models.core import Activo as _Activo
                        rows = (await self.db.execute(
                            select(_Activo.ACT_Codigo_Interno)
                            .where(_Activo.ACT_Activo.in_([m.ACT_Activo for m in vigentes]))
                        )).all()
                        activos_codigos = [r[0] for r in rows]
                    await send_notification(
                        "offboarding",
                        {
                            "persona_nombre": f"{persona.PER_Primer_Nombre} {persona.PER_Primer_Apellido}",
                            "persona_email": persona.PER_Email_Corporativo or "—",
                            "num_activos": len(activos_codigos),
                            "activos_lista": activos_codigos,
                            "usuario_desactivado": "Sí" if usuario_desactivado else "No",
                            "fecha": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                        },
                        # Persona saliente NO recibe (su email puede estar deshabilitado),
                        # solo admins.
                        to=(),
                    )
                except Exception:  # noqa: BLE001
                    pass

            return {
                "status": "success",
                "persona_id": str(persona_id),
                "movimientos_cerrados": cerrados,
                "activos_devueltos_a_bodega": len(activos_ids),
                "usuario_desactivado": usuario_desactivado,
                "persona_inactivada": True,
                "idempotent_noop": not algo_cambio,
            }
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "OFFBOARDING_FAILED")

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

            cerrado = await self.repo.cerrar_movimiento(vigente.MOV_Movimiento)
            if not cerrado:
                # Otro proceso lo cerró antes.
                raise HTTPException(409, detail="MOVEMENT_ALREADY_CLOSED")

            # Devolución → activo vuelve a estado "En Bodega" en la misma transacción.
            estado_bodega_id = await self._get_estado_id("%Bodega%")
            if estado_bodega_id:
                await self._set_activo_estado(schema.ACT_Activo, estado_bodega_id)

            await self.gov_repo.create_audit_log(
                "RETURN", "INV_MOVIMIENTO",
                {"activo": str(schema.ACT_Activo), "estado_nuevo": estado_bodega_id},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()

            # Notificación post-commit
            try:
                activo = await self.core_repo.get_by_id_simple(schema.ACT_Activo)
                persona = (await self.db.execute(
                    select(Persona).where(Persona.PER_Persona == vigente.PER_Persona)
                )).scalar_one_or_none()
                await send_notification(
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
                )
            except Exception:  # noqa: BLE001
                pass

            return {"status": "success", "message": "ASSET_RETURNED_SUCCESSFULLY"}
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def registrar_transferencia(
        self,
        schema: TransferenciaCreate,
        usuario_id: uuid.UUID | None = None,
        ip: str | None = None,
    ):
        try:
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

            tipo_mov = (await self.db.execute(
                select(TipoMovimiento).where(TipoMovimiento.TMO_Nombre.ilike("%Asignación%"))
            )).scalar_one_or_none()
            if not tipo_mov:
                raise HTTPException(500, detail="SYSTEM_CONFIG_ERROR_MISSING_ASSIGNMENT_TYPE")

            await self.repo.cerrar_movimiento(vigente.MOV_Movimiento)

            nuevo_mov = MovimientoCreate(
                ACT_Activo=schema.ACT_Activo,
                PER_Persona=schema.PER_Persona_Destino,
                ARE_Area=schema.ARE_Area_Destino,
                TMO_Tipo_Movimiento=tipo_mov.TMO_Tipo_Movimiento,
                MOV_Observacion=schema.MOV_Observacion or "Transferencia de custodia",
            )
            created = await self.repo.create_movimiento(nuevo_mov)

            # Transferencia: el activo sigue "Asignado", garantizamos el estado.
            estado_asignado_id = await self._get_estado_id("Asignado")
            if estado_asignado_id:
                await self._set_activo_estado(schema.ACT_Activo, estado_asignado_id)

            await self.gov_repo.create_audit_log(
                "TRANSFER", "INV_MOVIMIENTO",
                {
                    "activo": str(schema.ACT_Activo),
                    "de_persona": str(vigente.PER_Persona),
                    "a_persona": str(schema.PER_Persona_Destino),
                    "estado_nuevo": estado_asignado_id,
                },
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()

            # Notificación post-commit a origen, destino y admins
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
                await send_notification(
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
                )
            except Exception:  # noqa: BLE001
                pass
            return await self.repo.get_by_id_full(created.MOV_Movimiento)
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")
