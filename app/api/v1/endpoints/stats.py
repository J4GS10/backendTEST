"""Estadísticas: dashboard. Todos los roles de inventario, con los datos de su alcance."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_business
from app.db.session import get_read_db
from app.services.stats import StatsService

router = APIRouter()


@router.get("/dashboard", dependencies=[Depends(require_business)])
async def get_dashboard_metrics(db: AsyncSession = Depends(get_read_db)):
    """KPIs principales, calculados solo con las sedes del alcance del usuario."""
    service = StatsService(db)
    return await service.get_dashboard_stats()
