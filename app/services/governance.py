"""Servicio de Gobernanza: configuración global + acceso a auditoría."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.governance import AuditoriaSistema
from app.repositories.governance import GovernanceRepository
from app.schemas.governance import ConfigUpdate


class GovernanceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = GovernanceRepository(db)

    # =====================================================================
    # CONFIG
    # =====================================================================
    async def get_public_config(self):
        return await self.repo.get_config()

    async def update_config(
        self, schema: ConfigUpdate, usuario_id: uuid.UUID | None = None, ip: str | None = None
    ):
        config = await self.repo.update_config(schema)
        await self.repo.create_audit_log(
            "UPDATE", "SYS_CONFIGURACION",
            {"cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip_origen=ip,
        )
        try:
            await self.db.commit()
        except IntegrityError as e:
            await self.db.rollback()
            raise HTTPException(409, "INTEGRITY_CONSTRAINT_VIOLATED") from e
        return config

    # =====================================================================
    # AUDIT LOG — consulta paginada + filtros
    # =====================================================================
    async def list_audit_logs(
        self,
        skip: int = 0,
        limit: int = 50,
        accion: Optional[str] = None,
        entidad: Optional[str] = None,
        usuario_id: Optional[uuid.UUID] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ):
        conditions = []
        if accion:
            conditions.append(AuditoriaSistema.AUD_Accion == accion)
        if entidad:
            conditions.append(AuditoriaSistema.AUD_Entidad_Afectada == entidad)
        if usuario_id:
            conditions.append(AuditoriaSistema.USU_Usuario == usuario_id)
        if from_date:
            conditions.append(AuditoriaSistema.AUD_Fecha_Hora >= from_date)
        if to_date:
            conditions.append(AuditoriaSistema.AUD_Fecha_Hora <= to_date)

        # Total
        count_q = select(func.count()).select_from(AuditoriaSistema)
        if conditions:
            count_q = count_q.where(*conditions)
        total = (await self.db.execute(count_q)).scalar() or 0

        # Items
        q = select(AuditoriaSistema)
        if conditions:
            q = q.where(*conditions)
        q = q.order_by(desc(AuditoriaSistema.AUD_Fecha_Hora)).offset(skip).limit(limit)
        items = (await self.db.execute(q)).scalars().all()

        return {"total": total, "items": items}

    async def audit_summary(
        self,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> dict:
        """
        Resumen agregado para dashboards forenses:
          - por_accion: {CREATE: n, UPDATE: n, DELETE: n, ...}
          - por_entidad: {INV_ACTIVO: n, INV_USUARIO: n, ...}
          - total
        """
        conditions = []
        if from_date:
            conditions.append(AuditoriaSistema.AUD_Fecha_Hora >= from_date)
        if to_date:
            conditions.append(AuditoriaSistema.AUD_Fecha_Hora <= to_date)

        base = select(AuditoriaSistema.AUD_Accion, func.count()).group_by(AuditoriaSistema.AUD_Accion)
        if conditions:
            base = base.where(*conditions)
        por_accion = {row[0]: row[1] for row in (await self.db.execute(base)).all()}

        base2 = select(AuditoriaSistema.AUD_Entidad_Afectada, func.count()).group_by(
            AuditoriaSistema.AUD_Entidad_Afectada
        )
        if conditions:
            base2 = base2.where(*conditions)
        por_entidad = {row[0]: row[1] for row in (await self.db.execute(base2)).all()}

        total = sum(por_accion.values())
        return {
            "total": total,
            "por_accion": por_accion,
            "por_entidad": por_entidad,
            "from_date": from_date.isoformat() if from_date else None,
            "to_date": to_date.isoformat() if to_date else None,
        }
