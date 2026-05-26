"""Estadísticas: dashboard. Solo roles operativos (no CONSULTA)."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operativo
from app.db.session import get_db
from app.services.stats import StatsService

router = APIRouter()


@router.get("/dashboard", dependencies=[Depends(require_operativo)])
async def get_dashboard_metrics(db: AsyncSession = Depends(get_db)):
    """KPIs principales. Requiere rol TECNICO o superior."""
    service = StatsService(db)
    return await service.get_dashboard_stats()
