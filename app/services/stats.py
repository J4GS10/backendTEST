from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Activo
from app.models.catalogs import EstadoOperativo, TipoActivo
from app.models.organization import Persona, Departamento
from app.models.traceability import Mantenimiento, Movimiento
from app.models.software import Licencia, Software


class StatsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard_stats(self):
        db = self.db

        # --- Totales base ---
        total_activos = (await db.execute(select(func.count()).select_from(Activo))).scalar() or 0
        total_asignados = (await db.execute(
            select(func.count()).select_from(Movimiento).where(Movimiento.MOV_Fecha_Devolucion.is_(None))
        )).scalar() or 0

        # --- Activos por estado (Disponible/Asignado/En Bodega/En Reparación/Baja) ---
        rows_estado = (await db.execute(
            select(EstadoOperativo.EOP_Nombre, func.count(Activo.ACT_Activo))
            .select_from(EstadoOperativo)
            .join(Activo, Activo.EOP_Estado_Operativo == EstadoOperativo.EOP_Estado_Operativo, isouter=True)
            .group_by(EstadoOperativo.EOP_Nombre)
        )).all()
        por_estado = {nombre: cnt for nombre, cnt in rows_estado}

        # --- Activos por tipo de componente ---
        rows_tipo = (await db.execute(
            select(TipoActivo.TAC_Nombre, func.count(Activo.ACT_Activo))
            .select_from(TipoActivo)
            .join(Activo, Activo.TAC_Tipo_Activo == TipoActivo.TAC_Tipo_Activo, isouter=True)
            .group_by(TipoActivo.TAC_Nombre)
        )).all()
        por_tipo = [{"tipo": n, "total": c} for n, c in rows_tipo if c]

        # --- Activos asignados por departamento (movimiento vigente → persona → depto) ---
        rows_depto = (await db.execute(
            select(Departamento.DEP_Nombre, func.count(Movimiento.MOV_Movimiento))
            .select_from(Movimiento)
            .join(Persona, Persona.PER_Persona == Movimiento.PER_Persona)
            .join(Departamento, Departamento.DEP_Departamento == Persona.DEP_Departamento)
            .where(Movimiento.MOV_Fecha_Devolucion.is_(None))
            .group_by(Departamento.DEP_Nombre)
            .order_by(func.count(Movimiento.MOV_Movimiento).desc())
        )).all()
        por_departamento = [{"departamento": n, "total": c} for n, c in rows_depto]

        # --- Garantías por vencer (próximos 90 días) — ACCIONABLE ---
        hoy = date.today()
        limite = hoy + timedelta(days=90)
        rows_gar = (await db.execute(
            select(Activo.ACT_Codigo_Interno, Activo.ACT_Fin_Garantia)
            .where(Activo.ACT_Fin_Garantia.isnot(None),
                   Activo.ACT_Fin_Garantia >= hoy,
                   Activo.ACT_Fin_Garantia <= limite)
            .order_by(Activo.ACT_Fin_Garantia.asc())
            .limit(50)
        )).all()
        garantias_por_vencer = [
            {"codigo": c, "fin_garantia": f.isoformat() if f else None} for c, f in rows_gar
        ]
        vencidas = (await db.execute(
            select(func.count()).select_from(Activo)
            .where(Activo.ACT_Fin_Garantia.isnot(None), Activo.ACT_Fin_Garantia < hoy)
        )).scalar() or 0

        # --- Mantenimiento ---
        mant_abiertos = (await db.execute(
            select(func.count()).select_from(Mantenimiento).where(Mantenimiento.MAN_Fecha_Cierre.is_(None))
        )).scalar() or 0
        mant_total = (await db.execute(select(func.count()).select_from(Mantenimiento))).scalar() or 0
        costo_mantenimiento = (await db.execute(
            select(func.coalesce(func.sum(Mantenimiento.MAN_Costo_Total), 0))
        )).scalar() or 0

        # --- Valor del inventario (activo vs. baja) ---
        baja_id = (await db.execute(
            select(EstadoOperativo.EOP_Estado_Operativo).where(EstadoOperativo.EOP_Nombre.ilike("Baja"))
        )).scalar()
        costo_total = (await db.execute(
            select(func.coalesce(func.sum(Activo.ACT_Costo), 0))
            .where(Activo.EOP_Estado_Operativo != baja_id) if baja_id else
            select(func.coalesce(func.sum(Activo.ACT_Costo), 0))
        )).scalar() or 0

        # --- Licencias ---
        lic_total, lic_usadas = (await db.execute(
            select(func.coalesce(func.sum(Licencia.LIC_Cantidad_Total), 0),
                   func.coalesce(func.sum(Licencia.LIC_Cantidad_Usada), 0))
        )).one()
        rows_lic = (await db.execute(
            select(Software.SOF_Nombre, Licencia.LIC_Cantidad_Usada, Licencia.LIC_Cantidad_Total)
            .select_from(Licencia)
            .join(Software, Software.SOF_Software == Licencia.SOF_Software, isouter=True)
            .where(Licencia.LIC_Cantidad_Total > 0,
                   Licencia.LIC_Cantidad_Usada * 100 >= Licencia.LIC_Cantidad_Total * 80)
        )).all()
        licencias_por_agotar = [
            {"software": n or "—", "usadas": u, "total": tt} for n, u, tt in rows_lic
        ]

        return {
            # Compatibilidad con el dashboard anterior
            "activos_totales": total_activos,
            "activos_asignados": total_asignados,
            "activos_stock": total_activos - total_asignados,
            "licencias_total": int(lic_total or 0),
            "licencias_usadas": int(lic_usadas or 0),
            "licencias_disponibles": int((lic_total or 0) - (lic_usadas or 0)),
            "mantenimientos_abiertos": mant_abiertos,
            "mantenimientos_total": mant_total,
            # KPIs nuevos para decidir
            "disponibles_bodega": por_estado.get("Disponible", 0) + por_estado.get("En Bodega", 0),
            "en_reparacion": por_estado.get("En Reparación", 0),
            "en_baja": por_estado.get("Baja", 0),
            "por_estado": por_estado,
            "por_tipo": por_tipo,
            "por_departamento": por_departamento,
            "garantias_por_vencer": garantias_por_vencer,
            "garantias_por_vencer_total": len(garantias_por_vencer),
            "garantias_vencidas": vencidas,
            "costo_inventario": float(costo_total),
            "costo_mantenimiento": float(costo_mantenimiento),
            "licencias_por_agotar": licencias_por_agotar,
        }
