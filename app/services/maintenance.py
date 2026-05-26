"""Servicio de mantenimientos."""
from __future__ import annotations

from app.core.errors import internal_error
from app.core.transactional import commit_or_409

import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalogs import EstadoOperativo
from app.models.organization import Persona
from app.models.traceability import Mantenimiento
from app.repositories.core import CoreRepository
from app.repositories.governance import GovernanceRepository
from app.repositories.maintenance import MaintenanceRepository
from app.schemas.maintenance import (
    DetalleCreate,
    MantenimientoCierre,
    MantenimientoCreate,
    TipoMantenimientoCreate,
    TipoMantenimientoUpdate,
)


class MaintenanceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = MaintenanceRepository(db)
        self.gov_repo = GovernanceRepository(db)
        self.core_repo = CoreRepository(db)

    async def _commit(self):
        await commit_or_409(self.db, where="MaintenanceService")

    # =====================================================================
    # TIPOS
    # =====================================================================
    async def create_tipo(self, schema: TipoMantenimientoCreate, usuario_id=None, ip=None):
        obj = await self.repo.create_tipo(schema)
        await self.gov_repo.create_audit_log(
            "CREATE", "INV_TIPO_MANTENIMIENTO",
            {"nombre": schema.TMA_Nombre},
            usuario_id=usuario_id, ip_origen=ip,
        )
        await self._commit()
        return obj

    async def list_tipos(self):
        return await self.repo.get_tipos()

    async def get_tipo(self, id: int):
        obj = await self.repo.get_tipo_by_id(id)
        if not obj:
            raise HTTPException(404, "MAINTENANCE_TYPE_NOT_FOUND")
        return obj

    async def update_tipo(self, id: int, schema: TipoMantenimientoUpdate, usuario_id=None, ip=None):
        await self.get_tipo(id)
        obj = await self.repo.update_tipo(id, schema)
        await self.gov_repo.create_audit_log(
            "UPDATE", "INV_TIPO_MANTENIMIENTO",
            {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip_origen=ip,
        )
        await self._commit()
        return obj

    async def delete_tipo(self, id: int, usuario_id=None, ip=None):
        tipo = await self.get_tipo(id)
        if await self.repo.count_mantenimientos_by_tipo(id) > 0:
            raise HTTPException(409, "CANNOT_DELETE_TYPE_HAS_TICKETS")
        await self.repo.delete_tipo(id)
        await self.gov_repo.create_audit_log(
            "DELETE", "INV_TIPO_MANTENIMIENTO",
            {"id": id, "nombre": tipo.TMA_Nombre},
            usuario_id=usuario_id, ip_origen=ip,
        )
        await self._commit()

    # =====================================================================
    # MANTENIMIENTOS
    # =====================================================================
    async def list_mantenimientos(self, skip: int = 0, limit: int = 50):
        return await self.repo.get_all(skip, limit)

    async def get_mantenimiento(self, id: uuid.UUID):
        obj = await self.repo.get_by_id(id)
        if not obj:
            raise HTTPException(404, "MAINTENANCE_TICKET_NOT_FOUND")
        return obj

    async def registrar_mantenimiento(
        self, schema: MantenimientoCreate, usuario_id: uuid.UUID | None = None, ip: str | None = None,
    ):
        try:
            activo = await self.core_repo.get_by_id_simple(schema.ACT_Activo)
            if not activo:
                raise HTTPException(404, "ASSET_NOT_FOUND")

            persona = (await self.db.execute(
                select(Persona).where(Persona.PER_Persona == schema.PER_Persona_Solicita)
            )).scalar_one_or_none()
            if not persona:
                raise HTTPException(404, "REQUESTING_PERSON_NOT_FOUND")

            abierto = (await self.db.execute(
                select(Mantenimiento).where(
                    Mantenimiento.ACT_Activo == schema.ACT_Activo,
                    Mantenimiento.MAN_Fecha_Cierre.is_(None),
                )
            )).scalar_one_or_none()
            if abierto:
                raise HTTPException(409, "ASSET_ALREADY_HAS_OPEN_MAINTENANCE_TICKET")

            estado_reparacion = (await self.db.execute(
                select(EstadoOperativo).where(EstadoOperativo.EOP_Nombre.ilike("%Reparación%"))
            )).scalar_one_or_none()
            if estado_reparacion:
                activo.EOP_Estado_Operativo = estado_reparacion.EOP_Estado_Operativo

            mantenimiento = await self.repo.create_mantenimiento(schema)
            await self.gov_repo.create_audit_log(
                "CREATE", "INV_MANTENIMIENTO",
                {"activo": str(schema.ACT_Activo), "falla": schema.MAN_Descripcion_Falla[:200]},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self._commit()
            return mantenimiento
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def agregar_detalle(
        self, mantenimiento_id: uuid.UUID, schema: DetalleCreate, usuario_id=None, ip=None,
    ):
        mant = await self.get_mantenimiento(mantenimiento_id)
        if mant.MAN_Fecha_Cierre:
            raise HTTPException(400, "CANNOT_ADD_DETAILS_TO_CLOSED_TICKET")
        obj = await self.repo.add_detalle(mantenimiento_id, schema)
        await self.gov_repo.create_audit_log(
            "CREATE", "INV_DETALLE_MANT",
            {"mantenimiento_id": str(mantenimiento_id), "accion": schema.DMA_Accion_Realizada[:200]},
            usuario_id=usuario_id, ip_origen=ip,
        )
        await self._commit()
        return obj

    async def list_detalles(self, mantenimiento_id: uuid.UUID):
        await self.get_mantenimiento(mantenimiento_id)
        return await self.repo.list_detalles(mantenimiento_id)

    async def update_detalle(self, detalle_id: int, schema: DetalleCreate, usuario_id=None, ip=None):
        det = await self.repo.get_detalle_by_id(detalle_id)
        if not det:
            raise HTTPException(404, "MAINTENANCE_DETAIL_NOT_FOUND")
        mant = await self.repo.get_by_id(det.MAN_Mantenimiento)
        if mant and mant.MAN_Fecha_Cierre:
            raise HTTPException(400, "CANNOT_MODIFY_DETAILS_OF_CLOSED_TICKET")
        obj = await self.repo.update_detalle(detalle_id, schema)
        await self.gov_repo.create_audit_log(
            "UPDATE", "INV_DETALLE_MANT",
            {"detalle_id": detalle_id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip_origen=ip,
        )
        await self._commit()
        return obj

    async def delete_detalle(self, detalle_id: int, usuario_id=None, ip=None):
        det = await self.repo.get_detalle_by_id(detalle_id)
        if not det:
            raise HTTPException(404, "MAINTENANCE_DETAIL_NOT_FOUND")
        mant = await self.repo.get_by_id(det.MAN_Mantenimiento)
        if mant and mant.MAN_Fecha_Cierre:
            raise HTTPException(400, "CANNOT_DELETE_DETAILS_OF_CLOSED_TICKET")
        await self.repo.delete_detalle(detalle_id)
        await self.gov_repo.create_audit_log(
            "DELETE", "INV_DETALLE_MANT",
            {"detalle_id": detalle_id},
            usuario_id=usuario_id, ip_origen=ip,
        )
        await self._commit()

    async def cerrar_mantenimiento(
        self, mantenimiento_id: uuid.UUID, schema: MantenimientoCierre,
        usuario_id: uuid.UUID | None = None, ip: str | None = None,
    ):
        try:
            mant = await self.get_mantenimiento(mantenimiento_id)
            if mant.MAN_Fecha_Cierre:
                raise HTTPException(400, "TICKET_ALREADY_CLOSED")

            fecha = schema.MAN_Fecha_Cierre or datetime.utcnow()
            if fecha < mant.MAN_Fecha_Ingreso:
                raise HTTPException(400, "CLOSE_DATE_CANNOT_BE_BEFORE_ENTRY_DATE")

            closed = await self.repo.close_mantenimiento(
                mantenimiento_id, fecha_cierre=fecha, costo_total=schema.MAN_Costo_Total
            )

            estado_disponible = (await self.db.execute(
                select(EstadoOperativo).where(EstadoOperativo.EOP_Nombre.ilike("%Disponible%"))
            )).scalar_one_or_none()
            if estado_disponible:
                activo = await self.core_repo.get_by_id_simple(mant.ACT_Activo)
                if activo:
                    activo.EOP_Estado_Operativo = estado_disponible.EOP_Estado_Operativo

            await self.gov_repo.create_audit_log(
                "CLOSE", "INV_MANTENIMIENTO",
                {"ticket_id": str(mantenimiento_id), "costo_total": str(schema.MAN_Costo_Total)},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self._commit()
            return closed
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def delete_mantenimiento(self, mantenimiento_id: uuid.UUID, usuario_id=None, ip=None):
        mant = await self.get_mantenimiento(mantenimiento_id)
        if not mant.MAN_Fecha_Cierre:
            raise HTTPException(400, "CANNOT_DELETE_OPEN_TICKET")
        await self.repo.delete_mantenimiento(mantenimiento_id)
        await self.gov_repo.create_audit_log(
            "DELETE", "INV_MANTENIMIENTO",
            {"ticket_id": str(mantenimiento_id)},
            usuario_id=usuario_id, ip_origen=ip,
        )
        await self._commit()
