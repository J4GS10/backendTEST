"""
Servicio de Adjuntos. Maneja el almacenamiento en disco (volumen local) +
los metadatos en BD, de forma consistente:

- Validación de extensión (lista blanca) y tamaño máximo ANTES de escribir.
- Nombre en disco derivado de un uuid (nunca del nombre del cliente) → inmune a
  path traversal y colisiones.
- Si falla el commit en BD, el archivo recién escrito se elimina (no deja huérfanos).
- Si falla la escritura en disco, no se toca la BD.
"""
from __future__ import annotations

import os
import uuid

import structlog
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.storage import (
    StorageUnavailableError,
    storage_for_backend,
    storage_service,
)
from app.core.transactional import schedule_post_commit, transactional
from app.models.attachment import Adjunto
from app.models.core import Activo
from app.models.procurement import OrdenCompra
from app.repositories.attachment import AttachmentRepository
from app.repositories.governance import GovernanceRepository

_VALID_CATEGORIES = {"factura", "foto", "acta", "otro"}
log = structlog.get_logger("attachments")


class AttachmentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AttachmentRepository(db)
        self.gov_repo = GovernanceRepository(db)

    # --- Resolución de directorio por dueño (activo u orden) ---
    def _object_key_for(self, adjunto: Adjunto) -> str:
        if adjunto.ADJ_Object_Key:
            return adjunto.ADJ_Object_Key
        kind = "activos" if adjunto.ACT_Activo is not None else "ordenes"
        owner_id = adjunto.ACT_Activo or adjunto.OCO_Orden
        return f"{kind}/{owner_id}/{adjunto.ADJ_Nombre_Almacenado}"

    async def _ensure_activo(self, activo_id: uuid.UUID) -> Activo:
        obj = (await self.db.execute(
            select(Activo).where(Activo.ACT_Activo == activo_id)
        )).scalar_one_or_none()
        if not obj:
            raise HTTPException(404, "ASSET_NOT_FOUND")
        return obj

    async def _ensure_orden(self, orden_id: int) -> OrdenCompra:
        obj = (await self.db.execute(
            select(OrdenCompra).where(OrdenCompra.OCO_Orden == orden_id)
        )).scalar_one_or_none()
        if not obj:
            raise HTTPException(404, "PURCHASE_ORDER_NOT_FOUND")
        return obj

    # --- Listados ---
    async def list(self, activo_id: uuid.UUID):
        await self._ensure_activo(activo_id)
        return await self.repo.get_by_activo(activo_id)

    async def list_orden(self, orden_id: int):
        await self._ensure_orden(orden_id)
        return await self.repo.get_by_orden(orden_id)

    # --- Subida (genérica por dueño) ---
    async def upload(
        self, activo_id: uuid.UUID, file: UploadFile,
        categoria: str = "otro", descripcion: str | None = None,
        usuario_id: uuid.UUID | None = None, ip: str | None = None,
    ):
        await self._ensure_activo(activo_id)
        return await self._upload("activos", activo_id, {"ACT_Activo": activo_id},
                                  file, categoria, descripcion, usuario_id, ip)

    async def upload_orden(
        self, orden_id: int, file: UploadFile,
        categoria: str = "factura", descripcion: str | None = None,
        usuario_id: uuid.UUID | None = None, ip: str | None = None,
    ):
        await self._ensure_orden(orden_id)
        return await self._upload("ordenes", orden_id, {"OCO_Orden": orden_id},
                                  file, categoria, descripcion, usuario_id, ip)

    @transactional
    async def _upload(self, kind, owner_id, owner_fk: dict, file: UploadFile,
                      categoria, descripcion, usuario_id, ip):
        categoria = (categoria or "otro").lower()
        if categoria not in _VALID_CATEGORIES:
            raise HTTPException(400, "INVALID_ATTACHMENT_CATEGORY")

        original = file.filename or "archivo"
        ext = os.path.splitext(original)[1].lower()
        if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
            raise HTTPException(400, "FILE_TYPE_NOT_ALLOWED")

        content = await file.read()
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(content) > max_bytes:
            raise HTTPException(413, f"FILE_TOO_LARGE_MAX_MB:{settings.MAX_UPLOAD_SIZE_MB}")
        if len(content) == 0:
            raise HTTPException(400, "EMPTY_FILE")

        stored_name = f"{uuid.uuid4().hex}{ext}"
        object_key = f"{kind}/{owner_id}/{stored_name}"

        try:
            stored = await storage_service.put_bytes(
                object_key, content, file.content_type or None
            )
        except StorageUnavailableError as exc:
            raise HTTPException(503, str(exc)) from exc

        try:
            adjunto = Adjunto(
                ADJ_Nombre_Original=original[:255],
                ADJ_Nombre_Almacenado=stored_name,
                ADJ_Storage_Backend=stored.backend,
                ADJ_Bucket=stored.bucket,
                ADJ_Object_Key=stored.object_key,
                ADJ_Checksum_SHA256=stored.checksum_sha256,
                ADJ_Tipo_MIME=(file.content_type or None),
                ADJ_Tamano_Bytes=len(content),
                ADJ_Categoria=categoria,
                ADJ_Descripcion=descripcion,
                USU_Usuario=usuario_id,
                **owner_fk,
            )
            await self.repo.create(adjunto)
            await self.gov_repo.create_audit_log(
                "CREATE", "INV_ADJUNTO",
                {"dueno": f"{kind}:{owner_id}", "nombre": original[:255],
                 "categoria": categoria, "tamano": len(content)},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.flush()
            return adjunto
        except Exception:
            # The binary was written before the database row. Compensate only
            # when persistence fails so storage and metadata stay consistent.
            try:
                await storage_service.delete(stored.object_key, stored.bucket)
            except StorageUnavailableError:
                log.error("storage.compensation_failed", object_key=stored.object_key)
            raise

    async def get_for_download(self, id: uuid.UUID):
        adjunto = await self.repo.get_by_id(id)
        if not adjunto:
            raise HTTPException(404, "ATTACHMENT_NOT_FOUND")
        backend = adjunto.ADJ_Storage_Backend or "local"
        selected_storage = storage_for_backend(backend)
        try:
            content = await selected_storage.get_bytes(
                self._object_key_for(adjunto), adjunto.ADJ_Bucket
            )
        except StorageUnavailableError as exc:
            if backend == "local" and str(exc) == "ATTACHMENT_FILE_MISSING":
                raise HTTPException(410, "ATTACHMENT_FILE_MISSING") from exc
            raise HTTPException(503, str(exc)) from exc
        return adjunto, content

    @transactional
    async def delete(self, id: uuid.UUID, usuario_id=None, ip=None):
        adjunto = await self.repo.get_by_id(id)
        if not adjunto:
            raise HTTPException(404, "ATTACHMENT_NOT_FOUND")
        selected_storage = storage_for_backend(adjunto.ADJ_Storage_Backend or "local")
        object_key = self._object_key_for(adjunto)
        bucket = adjunto.ADJ_Bucket
        await self.repo.delete(id)
        await self.gov_repo.create_audit_log(
            "DELETE", "INV_ADJUNTO",
            {"id": str(id), "nombre": adjunto.ADJ_Nombre_Original},
            usuario_id=usuario_id, ip_origen=ip,
        )

        async def _delete_binary() -> None:
            try:
                await selected_storage.delete(object_key, bucket)
            except StorageUnavailableError as exc:
                log.error(
                    "storage.delete_orphaned",
                    object_key=object_key,
                    error=str(exc),
                )

        schedule_post_commit(self, _delete_binary)
