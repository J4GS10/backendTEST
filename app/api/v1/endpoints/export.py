"""Endpoints de exportación CSV. Streaming para datasets grandes."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime
from typing import Optional

from app.api.deps import (
    CurrentUser, get_client_ip, get_current_user, get_user_agent, require_audit_reader, require_export,
)
from app.core.errors import utcnow_naive
from app.core.limiter import limiter
from app.db.session import get_db, get_read_db
from app.services.export import ExportService
from app.services.report_i18n import (
    format_amount,
    format_iso_date,
    format_iso_datetime,
    normalize_lang,
    translate_catalog,
    yes_no,
)

router = APIRouter()


_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

# Encabezados legibles y profesionales por idioma (con tildes/ñ en español).
_CSV_HEADERS = {
    "activos": {
        "es": ["Código interno", "Número de serie", "Hostname", "Tipo de activo", "Marca", "Modelo",
               "Estado operativo", "Fecha de compra", "Vencimiento de garantía", "Costo"],
        "en": ["Internal code", "Serial number", "Hostname", "Asset type", "Brand", "Model",
               "Operational status", "Purchase date", "Warranty expiration", "Cost"],
        "it": ["Codice interno", "Numero di serie", "Hostname", "Tipo di asset", "Marca", "Modello",
               "Stato operativo", "Data di acquisto", "Scadenza garanzia", "Costo"],
    },
    "movimientos": {
        "es": ["Fecha de asignación", "Fecha de devolución", "Código del activo", "Número de serie",
               "Colaborador", "Correo electrónico", "Área", "Tipo de movimiento", "Observaciones"],
        "en": ["Assignment date", "Return date", "Asset code", "Serial number",
               "Employee", "Email", "Area", "Movement type", "Notes"],
        "it": ["Data di assegnazione", "Data di restituzione", "Codice asset", "Numero di serie",
               "Collaboratore", "Email", "Area", "Tipo di movimento", "Note"],
    },
    "consumibles": {
        "es": ["Nombre", "Categoría", "Unidad de medida", "Existencia actual", "Existencia mínima",
               "Bajo el mínimo", "Activo"],
        "en": ["Name", "Category", "Unit of measure", "Current stock", "Minimum stock",
               "Below minimum", "Active"],
        "it": ["Nome", "Categoria", "Unità di misura", "Giacenza attuale", "Giacenza minima",
               "Sotto la scorta minima", "Attivo"],
    },
    "proveedores": {
        "es": ["Nombre", "Identificación fiscal", "Contacto", "Correo electrónico", "Teléfono",
               "Dirección", "Activo"],
        "en": ["Name", "Tax ID", "Contact", "Email", "Phone", "Address", "Active"],
        "it": ["Nome", "Identificativo fiscale", "Referente", "Email", "Telefono", "Indirizzo", "Attivo"],
    },
    "ordenes": {
        "es": ["Número de orden", "Proveedor", "Fecha", "Estado", "Moneda", "Total", "Notas"],
        "en": ["Order number", "Supplier", "Date", "Status", "Currency", "Total", "Notes"],
        "it": ["Numero ordine", "Fornitore", "Data", "Stato", "Valuta", "Totale", "Note"],
    },
    "auditoria": {
        "es": ["Fecha y hora", "Acción", "Entidad afectada", "IP de origen", "Agente de usuario",
               "ID de usuario", "Detalle (JSON)"],
        "en": ["Date and time", "Action", "Affected entity", "Source IP", "User agent",
               "User ID", "Details (JSON)"],
        "it": ["Data e ora", "Azione", "Entità interessata", "IP di origine", "User agent",
               "ID utente", "Dettagli (JSON)"],
    },
}

# Nombre base del archivo descargado, por idioma.
_CSV_FILENAMES = {
    "activos": {"es": "activos", "en": "assets", "it": "asset"},
    "movimientos": {"es": "movimientos", "en": "movements", "it": "movimenti"},
    "consumibles": {"es": "consumibles", "en": "consumables", "it": "materiali_di_consumo"},
    "proveedores": {"es": "proveedores", "en": "suppliers", "it": "fornitori"},
    "ordenes": {"es": "ordenes_de_compra", "en": "purchase_orders", "it": "ordini_di_acquisto"},
    "auditoria": {"es": "auditoria", "en": "audit_log", "it": "registro_audit"},
}


def _lang(lang: str | None) -> str:
    return normalize_lang(lang)


def _headers(name: str, lang: str | None) -> list[str]:
    return _CSV_HEADERS[name][_lang(lang)]


def _filename(name: str, lang: str | None) -> str:
    return _CSV_FILENAMES[name][_lang(lang)]


def _yes_no(value: bool, lang: str | None) -> str:
    return yes_no(bool(value), lang)


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


def _fmt_dt(value) -> str:
    """Fecha/hora legible para reportes: 'YYYY-MM-DD HH:MM:SS' (sin la 'T' ISO
    ni microsegundos). Formato más profesional para usuarios de negocio."""
    return format_iso_datetime(value)


def _csv_response(headers: list[str], rows, filename_prefix: str) -> StreamingResponse:
    """Genera un CSV en memoria y lo retorna como streaming."""
    buf = io.StringIO()
    # BOM UTF-8: hace que Microsoft Excel (Windows) detecte la codificación y
    # muestre correctamente los acentos/ñ. Sin esto, "Devolución" se ve roto.
    buf.write("\ufeff")
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_safe_cell(c) for c in row])
    buf.seek(0)
    fname = f"{filename_prefix}_{utcnow_naive().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/activos.csv", dependencies=[Depends(require_export)])
@limiter.limit("10/minute")
async def export_activos_csv(
    request: Request,
    db: AsyncSession = Depends(get_read_db),
    lang: str = Query("es", pattern="^(es|en|it)$"),
):
    """Exporta todos los activos a CSV (incluye marca/modelo/tipo/estado)."""
    activos = await ExportService(db).list_assets()

    headers = _headers("activos", lang)
    rows = []
    for a in activos:
        modelo = a.modelo
        rows.append([
            a.ACT_Codigo_Interno,
            a.ACT_Serie_Fabricante,
            a.ACT_Hostname or "",
            translate_catalog("tipo_activo", a.tipo_activo.TAC_Nombre, lang) if a.tipo_activo else "",
            modelo.marca.MAR_Nombre if modelo and modelo.marca else "",
            modelo.MOD_Nombre if modelo else "",
            translate_catalog("estado_operativo", a.estado_operativo.EOP_Nombre, lang)
            if a.estado_operativo else "",
            format_iso_date(a.ACT_Fecha_Compra),
            format_iso_date(a.ACT_Fin_Garantia),
            format_amount(a.ACT_Costo),
        ])
    return _csv_response(headers, rows, _filename("activos", lang))


@router.get("/movimientos.csv", dependencies=[Depends(require_export)])
@limiter.limit("10/minute")
async def export_movimientos_csv(
    request: Request,
    db: AsyncSession = Depends(get_read_db),
    limit: int = Query(5000, le=10000),
    lang: str = Query("es", pattern="^(es|en|it)$"),
):
    """Exporta los movimientos a CSV."""
    movs = await ExportService(db).list_movements(limit)
    headers = _headers("movimientos", lang)
    rows = []
    for m in movs:
        rows.append([
            _fmt_dt(m.MOV_Fecha_Asignacion),
            _fmt_dt(m.MOV_Fecha_Devolucion),
            m.activo.ACT_Codigo_Interno if m.activo else "",
            m.activo.ACT_Serie_Fabricante if m.activo else "",
            f"{m.persona.PER_Primer_Nombre} {m.persona.PER_Primer_Apellido}" if m.persona else "",
            m.persona.PER_Email_Corporativo if m.persona else "",
            m.area.ARE_Nombre if m.area else "",
            translate_catalog("tipo_movimiento", m.tipo_movimiento.TMO_Nombre, lang)
            if m.tipo_movimiento else "",
            m.MOV_Observacion or "",
        ])
    return _csv_response(headers, rows, _filename("movimientos", lang))


@router.get("/consumibles.csv", dependencies=[Depends(require_export)])
@limiter.limit("10/minute")
async def export_consumibles_csv(
    request: Request,
    db: AsyncSession = Depends(get_read_db),
    lang: str = Query("es", pattern="^(es|en|it)$"),
):
    """Exporta los consumibles a CSV (con stock y flag de bajo stock)."""
    items = await ExportService(db).list_consumables()
    headers = _headers("consumibles", lang)
    rows = [[
        c.CON_Nombre, c.CON_Categoria or "", translate_catalog("unidad", c.CON_Unidad, lang),
        c.CON_Stock_Actual, c.CON_Stock_Minimo,
        _yes_no(c.CON_Stock_Minimo > 0 and c.CON_Stock_Actual <= c.CON_Stock_Minimo, lang),
        _yes_no(c.CON_Activo, lang),
    ] for c in items]
    return _csv_response(headers, rows, _filename("consumibles", lang))


@router.get("/proveedores.csv", dependencies=[Depends(require_export)])
@limiter.limit("10/minute")
async def export_proveedores_csv(
    request: Request,
    db: AsyncSession = Depends(get_read_db),
    lang: str = Query("es", pattern="^(es|en|it)$"),
):
    """Exporta los proveedores a CSV."""
    items = await ExportService(db).list_providers()
    headers = _headers("proveedores", lang)
    rows = [[
        p.PRV_Nombre, p.PRV_Identificacion_Fiscal or "", p.PRV_Contacto or "",
        p.PRV_Email or "", p.PRV_Telefono or "", p.PRV_Direccion or "",
        _yes_no(p.PRV_Activo, lang),
    ] for p in items]
    return _csv_response(headers, rows, _filename("proveedores", lang))


@router.get("/ordenes.csv", dependencies=[Depends(require_export)])
@limiter.limit("10/minute")
async def export_ordenes_csv(
    request: Request,
    db: AsyncSession = Depends(get_read_db),
    lang: str = Query("es", pattern="^(es|en|it)$"),
):
    """Exporta las órdenes de compra a CSV (cabecera, sin líneas)."""
    items = await ExportService(db).list_orders()
    headers = _headers("ordenes", lang)
    rows = [[
        o.OCO_Numero, o.proveedor.PRV_Nombre if o.proveedor else "",
        format_iso_date(o.OCO_Fecha), translate_catalog("estado_orden", o.OCO_Estado, lang), o.OCO_Moneda,
        format_amount(o.OCO_Total), o.OCO_Notas or "",
    ] for o in items]
    return _csv_response(headers, rows, _filename("ordenes", lang))


@router.get("/auditoria.csv", dependencies=[Depends(require_audit_reader)])
@limiter.limit("5/minute")
async def export_auditoria_csv(
    request: Request,
    # Depends explícito: con `from __future__ import annotations` y el decorador
    # del limitador, FastAPI no resolvería el alias `CurrentUser`.
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db),
    write_db: AsyncSession = Depends(get_db),
    limit: int = Query(10000, le=50000),
    from_date: Optional[datetime] = Query(None, description="ISO timestamp inicial"),
    to_date: Optional[datetime] = Query(None, description="ISO timestamp final"),
    lang: str = Query("es", pattern="^(es|en|it)$"),
):
    """
    Exporta la bitácora de auditoría (filtrada por el alcance del lector).
    La propia exportación queda registrada: quién, cuándo y qué rango.
    """
    import json
    from app.repositories.governance import GovernanceRepository
    events = await ExportService(db).list_audit_events(limit, from_date=from_date, to_date=to_date)
    await GovernanceRepository(write_db).create_audit_log(
        accion="AUDIT_EXPORT", entidad="INV_AUDITORIA_SISTEMA",
        snapshot={"registros": len(events), "desde": from_date, "hasta": to_date, "idioma": lang},
        usuario_id=current_user.USU_Usuario,
        ip_origen=get_client_ip(request), user_agent=get_user_agent(request),
    )
    await write_db.commit()
    headers = _headers("auditoria", lang)
    rows = []
    for ev in events:
        rows.append([
            _fmt_dt(ev.AUD_Fecha_Hora),
            translate_catalog("accion_auditoria", ev.AUD_Accion, lang),
            ev.AUD_Entidad_Afectada,
            ev.AUD_IP_Origen or "",
            ev.AUD_User_Agent or "",
            str(ev.USU_Usuario) if ev.USU_Usuario else "",
            json.dumps(ev.AUD_Snapshot_JSON, ensure_ascii=False) if ev.AUD_Snapshot_JSON else "",
        ])
    return _csv_response(headers, rows, _filename("auditoria", lang))
