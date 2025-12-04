from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.traceability import TraceabilityService
from app.schemas.traceability import (
    TipoMovimientoCreate, TipoMovimientoResponse,
    MovimientoCreate, MovimientoResponse, ActaLoteRequest
)
from fastapi.responses import StreamingResponse
import uuid
from datetime import datetime

router = APIRouter()

def get_service(db: AsyncSession = Depends(get_db)) -> TraceabilityService:
    return TraceabilityService(db)

# --- TIPOS DE MOVIMIENTO ---
@router.post("/tipos", response_model=TipoMovimientoResponse, status_code=201)
async def create_tipo_movimiento(schema: TipoMovimientoCreate, service: TraceabilityService = Depends(get_service)):
    return await service.create_tipo_movimiento(schema)

@router.get("/tipos", response_model=List[TipoMovimientoResponse])
async def list_tipos(service: TraceabilityService = Depends(get_service)):
    return await service.list_tipos_movimiento()

@router.get("/movimientos", response_model=List[MovimientoResponse])
async def list_movimientos(service: TraceabilityService = Depends(get_service)):
    """
    Obtiene el historial completo de movimientos (Bitácora).
    """
    return await service.list_movimientos()

@router.post("/movimientos", response_model=MovimientoResponse, status_code=201)

# --- TRANSACCIONES (ASIGNAR) ---
@router.post("/movimientos", response_model=MovimientoResponse, status_code=201)
async def registrar_movimiento(schema: MovimientoCreate, service: TraceabilityService = Depends(get_service)):
    """
    Registra un movimiento (Asignación/Préstamo).
    Automáticamente cierra cualquier asignación vigente previa del mismo activo.
    """
    return await service.registrar_movimiento(schema)

@router.get("/acta/{movimiento_id}", response_class=StreamingResponse)
async def descargar_acta(
    movimiento_id: uuid.UUID,
    service: TraceabilityService = Depends(get_service), # Nota: Debemos inyectar DocumentService
    db: AsyncSession = Depends(get_db)
):
    """
    Genera y descarga el Acta de Entrega en formato Word (.docx).
    """
    # Instanciamos el servicio de documentos aquí o lo inyectamos
    from app.services.documents import DocumentService
    doc_service = DocumentService(db)
    
    buffer = await doc_service.generar_acta_entrega(movimiento_id)
    
    filename = f"Acta_Entrega_{movimiento_id}.docx"
    
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.post("/acta/lote", response_class=StreamingResponse)
async def descargar_acta_multiple(
    request: ActaLoteRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Genera una sola Acta PDF/Word para múltiples activos.
    Requiere que todos los movimientos sean de la misma persona.
    """
    from app.services.documents import DocumentService
    doc_service = DocumentService(db)
    
    buffer = await doc_service.generar_acta_multiple(request.movimientos_ids)
    
    filename = f"Acta_Entrega_Lote_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
    
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
