from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from app.models.core import Activo
from app.models.traceability import Movimiento
from app.models.software import Licencia

class StatsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard_stats(self):
        # 1. Total Activos
        res_activos = await self.db.execute(select(func.count()).select_from(Activo))
        total_activos = res_activos.scalar()

        # 2. Activos Asignados (En uso)
        # Asumimos que el estado "Asignado" tiene ID conocido o lo buscamos, 
        # pero para ser agnósticos, contamos Movimientos vigentes.
        res_asignados = await self.db.execute(
            select(func.count()).select_from(Movimiento).where(Movimiento.MOV_Fecha_Devolucion == None)
        )
        total_asignados = res_asignados.scalar()

        # 3. Total Licencias Usadas vs Total
        res_lic = await self.db.execute(select(func.sum(Licencia.LIC_Cantidad_Total), func.sum(Licencia.LIC_Cantidad_Usada)))
        lic_total, lic_usadas = res_lic.one()
        
        return {
            "activos_totales": total_activos or 0,
            "activos_asignados": total_asignados or 0,
            "activos_stock": (total_activos or 0) - (total_asignados or 0),
            "licencias_total": lic_total or 0,
            "licencias_usadas": lic_usadas or 0,
            "licencias_disponibles": (lic_total or 0) - (lic_usadas or 0)
        }