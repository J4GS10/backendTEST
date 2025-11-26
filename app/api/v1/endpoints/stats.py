from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.stats import StatsService
from app.api import deps

router = APIRouter()

@router.get("/dashboard", dependencies=[Depends(deps.get_current_user)])
async def get_dashboard_metrics(db: AsyncSession = Depends(get_db)):
    service = StatsService(db)
    return await service.get_dashboard_stats()