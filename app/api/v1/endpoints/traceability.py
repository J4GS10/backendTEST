"""Trazabilidad: movimientos, devoluciones, transferencias, actas."""
from datetime import datetime
from typing import List
import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_client_ip, require_admin, require_operativo
from app.api.idempotency import idempotency_guard, _IdempotencyGuard
from app.core.limiter import limiter
from app.db.session import get_db
from app.schemas.traceability import (
    ActaLoteRequest,
    DevolucionCreate,
    MovimientoCreate,
    MovimientoResponse,
    TipoMovimientoCreate,
    TipoMovimientoResponse,
    TipoMovimientoUpdate,
    TransferenciaCreate,
)
from app.services.traceability import TraceabilityService

router = APIRouter()

ADMIN = [Depends(require_admin)]
OPERATIVO = [Depends(require_operativo)]


def get_service(db: AsyncSession = Depends(get_db)) -> TraceabilityService:
    return TraceabilityService(db)


def _ctx(request: Request, user: CurrentUser) -> dict:
    return {"usuario_id": user.USU_Usuario, "ip": get_client_ip(request)}


# ================= TIPOS DE MOVIMIENTO =================
@router.get("/tipos", response_model=List[TipoMovimientoResponse])
async def list_tipos(service: TraceabilityService = Depends(get_service)):
    return await service.list_tipos_movimiento()


@router.get("/tipos/{id}", response_model=TipoMovimientoResponse)
async def get_tipo_movimiento(id: int, service: TraceabilityService = Depends(get_service)):
    obj = await service.repo.get_tipo_by_id(id)
    if not obj:
        from fastapi import HTTPException
        raise HTTPException(404, "MOVEMENT_TYPE_NOT_FOUND")
    return obj


@router.post("/tipos", response_model=TipoMovimientoResponse, status_code=201, dependencies=ADMIN)
async def create_tipo_movimiento(
    schema: TipoMovimientoCreate, request: Request, current_user: CurrentUser,
    service: TraceabilityService = Depends(get_service),
):
    return await service.create_tipo_movimiento(schema, **_ctx(request, current_user))


@router.patch("/tipos/{id}", response_model=TipoMovimientoResponse, dependencies=ADMIN)
async def update_tipo_movimiento(
    id: int, schema: TipoMovimientoUpdate, request: Request, current_user: CurrentUser,
    service: TraceabilityService = Depends(get_service),
):
    return await service.update_tipo_movimiento(id, schema, **_ctx(request, current_user))


@router.delete("/tipos/{id}", status_code=204, dependencies=ADMIN)
async def delete_tipo_movimiento(
    id: int, request: Request, current_user: CurrentUser,
    service: TraceabilityService = Depends(get_service),
):
    await service.delete_tipo_movimiento(id, **_ctx(request, current_user))


# ================= MOVIMIENTOS =================
@router.get("/movimientos", response_model=List[MovimientoResponse])
async def list_movimientos(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    service: TraceabilityService = Depends(get_service),
):
    """Historial paginado de movimientos (bitácora)."""
    return await service.list_movimientos(skip, limit)


@router.post("/movimientos", response_model=MovimientoResponse, status_code=201, dependencies=OPERATIVO)
@limiter.limit("60/minute")
async def registrar_movimiento(
    schema: MovimientoCreate, request: Request, current_user: CurrentUser,
    service: TraceabilityService = Depends(get_service),
    idempotency: _IdempotencyGuard = Depends(idempotency_guard),
):
    """
    Asigna un activo. Cierra automáticamente la asignación vigente previa.
    Soporta 'Idempotency-Key' para deduplicar reintentos.
    """
    cached = await idempotency.lookup()
    if cached is not None:
        return cached

    result = await service.registrar_movimiento(schema, **_ctx(request, current_user))
    await idempotency.store(result, status_code=201)
    return result


@router.post("/devolucion", status_code=200, dependencies=OPERATIVO)
@limiter.limit("60/minute")
async def registrar_devolucion(
    schema: DevolucionCreate, request: Request, current_user: CurrentUser,
    service: TraceabilityService = Depends(get_service),
):
    """Cierra la asignación activa del activo."""
    return await service.registrar_devolucion(schema, **_ctx(request, current_user))


@router.post("/transferencia", response_model=MovimientoResponse, status_code=201, dependencies=OPERATIVO)
@limiter.limit("30/minute")
async def registrar_transferencia(
    schema: TransferenciaCreate, request: Request, current_user: CurrentUser,
    service: TraceabilityService = Depends(get_service),
):
    """Transferencia atómica de custodia."""
    return await service.registrar_transferencia(schema, **_ctx(request, current_user))


# ================= HISTORIAL POR ACTIVO =================
@router.get("/activo/{activo_id}/historial", response_model=List[MovimientoResponse])
async def historial_activo(
    activo_id: uuid.UUID,
    service: TraceabilityService = Depends(get_service),
):
    """Historial completo de movimientos (asignación, devolución, transferencia) de un activo."""
    return await service.repo.get_historial_activo(activo_id)


# ================= FLUJOS POR PERSONA =================
@router.get("/persona/{persona_id}/asignaciones", response_model=List[MovimientoResponse])
async def get_asignaciones_persona(
    persona_id: uuid.UUID,
    service: TraceabilityService = Depends(get_service),
):
    """Lista los activos actualmente bajo custodia de una persona."""
    return await service.asignaciones_vigentes_persona(persona_id)


@router.post(
    "/persona/{persona_id}/offboarding",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("10/minute")
async def offboarding_persona(
    persona_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    desactivar_usuario: bool = Query(True, description="Si la persona tiene usuario, desactivarlo y revocar tokens"),
    service: TraceabilityService = Depends(get_service),
):
    """
    OFFBOARDING ATÓMICO: salida de empleado.
    En una sola transacción:
      - Cierra todos sus movimientos vigentes (los activos vuelven al inventario).
      - Cambia el estado operativo de esos activos a 'En Bodega'.
      - Si tiene usuario, lo desactiva y revoca todos sus tokens.
      - Marca a la persona como inactiva.
      - Registra un único evento OFFBOARDING en auditoría con snapshot completo.
    """
    return await service.offboarding_persona(
        persona_id,
        desactivar_usuario=desactivar_usuario,
        usuario_id=current_user.USU_Usuario,
        ip=get_client_ip(request),
    )


# ================= ACTAS (documentos Word / PDF) =================
_ACTA_MEDIA = {
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "pdf": ("application/pdf", "pdf"),
}


def _acta_response(buffer, filename_base: str, formato: str) -> StreamingResponse:
    media_type, ext = _ACTA_MEDIA.get((formato or "docx").lower(), _ACTA_MEDIA["docx"])
    return StreamingResponse(
        buffer,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.{ext}"'},
    )


@router.get("/acta/{movimiento_id}", response_class=StreamingResponse, dependencies=OPERATIVO)
async def descargar_acta(
    movimiento_id: uuid.UUID,
    formato: str = Query("docx", pattern="^(docx|pdf)$", description="Formato: docx o pdf"),
    tipo: str = Query("entrega", pattern="^(entrega|descargo)$",
                      description="entrega (handover) o descargo (devolución/liberación)"),
    mensajero: str | None = Query(None, max_length=120,
                                  description="Nombre del mensajero externo que recibe (opcional)"),
    db: AsyncSession = Depends(get_db),
):
    """Genera el Acta de Entrega o la Hoja de Descargo (devolución) en Word o PDF."""
    from app.services.documents import DocumentService
    doc_service = DocumentService(db)
    buffer = await doc_service.generar_acta_entrega(movimiento_id, formato=formato, tipo=tipo, mensajero=mensajero)
    nombre = "Descargo" if tipo == "descargo" else "Entrega"
    return _acta_response(buffer, f"Acta_{nombre}_{movimiento_id}", formato)


@router.post("/acta/lote", response_class=StreamingResponse, dependencies=OPERATIVO)
async def descargar_acta_multiple(
    payload: ActaLoteRequest,
    formato: str = Query("docx", pattern="^(docx|pdf)$", description="Formato: docx o pdf"),
    tipo: str = Query("entrega", pattern="^(entrega|descargo)$",
                      description="entrega o descargo"),
    mensajero: str | None = Query(None, max_length=120,
                                  description="Nombre del mensajero externo que recibe (opcional)"),
    db: AsyncSession = Depends(get_db),
):
    """Genera una sola Acta/Hoja (Word o PDF) para múltiples movimientos."""
    if len(payload.movimientos_ids) > 50:
        from fastapi import HTTPException
        raise HTTPException(400, "TOO_MANY_MOVEMENTS_REQUESTED")

    from app.services.documents import DocumentService
    doc_service = DocumentService(db)
    buffer = await doc_service.generar_acta_multiple(payload.movimientos_ids, formato=formato, tipo=tipo, mensajero=mensajero)
    nombre = "Descargo" if tipo == "descargo" else "Entrega"
    filename = f"Acta_{nombre}_Lote_{datetime.now().strftime('%Y%m%d_%H%M')}"
    return _acta_response(buffer, filename, formato)
