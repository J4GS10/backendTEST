"""Endpoints de exportación CSV. Streaming para datasets grandes."""
from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_admin, require_super_admin
from app.core.limiter import limiter
from app.db.session import get_db
from app.repositories.core import CoreRepository
from app.repositories.traceability import TraceabilityRepository
from app.services.governance import GovernanceService

router = APIRouter()


_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value) -> str:
    """
    Neutraliza fórmulas para prevenir CSV injection en Excel/Sheets.
    Un valor que empieza con = + - @ tab cr se prefija con comilla simple,
    evitando que el visor lo interprete como fórmula ejecutable.
    """
    s = "" if value is None else str(value)
    if s and s[0] in _CSV_INJECTION_PREFIXES:
        return "'" + s
    return s


def _csv_response(headers: list[str], rows, filename_prefix: str) -> StreamingResponse:
    """Genera un CSV en memoria y lo retorna como streaming."""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_safe_cell(c) for c in row])
    buf.seek(0)
    fname = f"{filename_prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/activos.csv", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def export_activos_csv(request: Request, db: AsyncSession = Depends(get_db)):
    """Exporta todos los activos a CSV (incluye marca/modelo/tipo/estado)."""
    repo = CoreRepository(db)
    activos = await repo.get_all(skip=0, limit=10000)

    # Resolver nombres con joins ligeros
    from sqlalchemy import select
    from app.models.catalogs import EstadoOperativo, Marca, Modelo, TipoActivo

    tipos = {t.TAC_Tipo_Activo: t.TAC_Nombre for t in (await db.execute(select(TipoActivo))).scalars()}
    modelos = {m.MOD_Modelo: m for m in (await db.execute(select(Modelo))).scalars()}
    marcas = {m.MAR_Marca: m.MAR_Nombre for m in (await db.execute(select(Marca))).scalars()}
    estados = {e.EOP_Estado_Operativo: e.EOP_Nombre for e in (await db.execute(select(EstadoOperativo))).scalars()}

    headers = [
        "Codigo_Interno", "Serie_Fabricante", "Hostname", "Tipo_Activo",
        "Marca", "Modelo", "Estado_Operativo", "Fecha_Compra", "Fin_Garantia", "Costo",
    ]
    rows = []
    for a in activos:
        modelo = modelos.get(a.MOD_Modelo)
        rows.append([
            a.ACT_Codigo_Interno,
            a.ACT_Serie_Fabricante,
            a.ACT_Hostname or "",
            tipos.get(a.TAC_Tipo_Activo, ""),
            marcas.get(modelo.MAR_Marca, "") if modelo else "",
            modelo.MOD_Nombre if modelo else "",
            estados.get(a.EOP_Estado_Operativo, ""),
            a.ACT_Fecha_Compra.isoformat() if a.ACT_Fecha_Compra else "",
            a.ACT_Fin_Garantia.isoformat() if a.ACT_Fin_Garantia else "",
            str(a.ACT_Costo or ""),
        ])
    return _csv_response(headers, rows, "activos")


@router.get("/movimientos.csv", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def export_movimientos_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(5000, le=10000),
):
    """Exporta los movimientos a CSV."""
    repo = TraceabilityRepository(db)
    movs = await repo.get_all_movimientos(skip=0, limit=limit)
    headers = [
        "Fecha_Asignacion", "Fecha_Devolucion", "Activo_Codigo", "Activo_Serie",
        "Persona", "Email", "Area", "Tipo_Movimiento", "Observacion",
    ]
    rows = []
    for m in movs:
        rows.append([
            m.MOV_Fecha_Asignacion.isoformat() if m.MOV_Fecha_Asignacion else "",
            m.MOV_Fecha_Devolucion.isoformat() if m.MOV_Fecha_Devolucion else "",
            m.activo.ACT_Codigo_Interno if m.activo else "",
            m.activo.ACT_Serie_Fabricante if m.activo else "",
            f"{m.persona.PER_Primer_Nombre} {m.persona.PER_Primer_Apellido}" if m.persona else "",
            m.persona.PER_Email_Corporativo if m.persona else "",
            m.area.ARE_Nombre if m.area else "",
            m.tipo_movimiento.TMO_Nombre if m.tipo_movimiento else "",
            m.MOV_Observacion or "",
        ])
    return _csv_response(headers, rows, "movimientos")


@router.get("/auditoria.csv", dependencies=[Depends(require_super_admin)])
@limiter.limit("5/minute")
async def export_auditoria_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(10000, le=50000),
):
    """Exporta el log de auditoría completo. Solo SUPER_ADMIN."""
    import json
    service = GovernanceService(db)
    result = await service.list_audit_logs(skip=0, limit=limit)
    headers = ["Fecha_Hora", "Accion", "Entidad_Afectada", "IP_Origen", "User_Agent", "Usuario_Id", "Snapshot_JSON"]
    rows = []
    for ev in result["items"]:
        rows.append([
            ev.AUD_Fecha_Hora.isoformat() if ev.AUD_Fecha_Hora else "",
            ev.AUD_Accion,
            ev.AUD_Entidad_Afectada,
            ev.AUD_IP_Origen or "",
            ev.AUD_User_Agent or "",
            str(ev.USU_Usuario) if ev.USU_Usuario else "",
            json.dumps(ev.AUD_Snapshot_JSON, ensure_ascii=False) if ev.AUD_Snapshot_JSON else "",
        ])
    return _csv_response(headers, rows, "auditoria")
