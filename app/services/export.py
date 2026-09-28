"""Orquestación de consultas de reporting para exportaciones."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.consumable import ConsumibleRepository
from app.repositories.core import CoreRepository
from app.repositories.procurement import ProcurementRepository
from app.repositories.traceability import TraceabilityRepository
from app.services.governance import GovernanceService


class ExportService:
    def __init__(self, db: AsyncSession):
        self.core_repo = CoreRepository(db)
        self.trace_repo = TraceabilityRepository(db)
        self.consumable_repo = ConsumibleRepository(db)
        self.procurement_repo = ProcurementRepository(db)
        self.governance_service = GovernanceService(db)

    async def list_assets(self, limit: int = 10000):
        return await self.core_repo.get_all_for_export(limit=limit)

    async def list_movements(self, limit: int):
        return await self.trace_repo.get_all_movimientos(skip=0, limit=limit)

    async def list_consumables(self):
        return await self.consumable_repo.get_all()

    async def list_providers(self):
        return await self.procurement_repo.get_proveedores()

    async def list_orders(self):
        return await self.procurement_repo.list_ordenes()

    async def list_audit_events(self, limit: int, from_date=None, to_date=None):
        result = await self.governance_service.list_audit_logs(
            skip=0, limit=limit, from_date=from_date, to_date=to_date,
        )
        return result["items"]

