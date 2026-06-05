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

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import internal_error
from app.models.attachment import Adjunto
from app.models.core import Activo
from app.models.procurement import OrdenCompra
from app.repositories.attachment import AttachmentRepository
from app.repositories.governance import GovernanceRepository

_VALID_CATEGORIES = {"factura", "foto", "acta", "otro"}


class AttachmentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AttachmentRepository(db)
        self.gov_repo = GovernanceRepository(db)

    # --- Resolución de directorio por dueño (activo u orden) ---
    def _dir(self, kind: str, owner_id) -> str:
        return os.path.join(settings.UPLOAD_DIR, kind, str(owner_id))

    def _dir_for(self, adjunto: Adjunto) -> str:
        if adjunto.ACT_Activo is not None:
            return self._dir("activos", adjunto.ACT_Activo)
        return self._dir("ordenes", adjunto.OCO_Orden)

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
        target_dir = self._dir(kind, owner_id)
        os.makedirs(target_dir, exist_ok=True)
        abs_path = os.path.join(target_dir, stored_name)

        try:
            with open(abs_path, "wb") as fh:
                fh.write(content)
        except OSError as e:
            raise internal_error(e, "STORAGE_WRITE_FAILED")

        try:
            adjunto = Adjunto(
                ADJ_Nombre_Original=original[:255],
                ADJ_Nombre_Almacenado=stored_name,
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
            await self.db.commit()
            await self.db.refresh(adjunto)
            return adjunto
        except HTTPException:
            await self.db.rollback(); _safe_remove(abs_path); raise
        except Exception as e:
            await self.db.rollback(); _safe_remove(abs_path)
            raise internal_error(e, "TRANSACTION_FAILED")

    async def get_for_download(self, id: uuid.UUID):
        adjunto = await self.repo.get_by_id(id)
        if not adjunto:
            raise HTTPException(404, "ATTACHMENT_NOT_FOUND")
        abs_path = os.path.join(self._dir_for(adjunto), adjunto.ADJ_Nombre_Almacenado)
        if not os.path.isfile(abs_path):
            raise HTTPException(410, "ATTACHMENT_FILE_MISSING")
        return adjunto, abs_path

    async def delete(self, id: uuid.UUID, usuario_id=None, ip=None):
        try:
            adjunto = await self.repo.get_by_id(id)
            if not adjunto:
                raise HTTPException(404, "ATTACHMENT_NOT_FOUND")
            abs_path = os.path.join(self._dir_for(adjunto), adjunto.ADJ_Nombre_Almacenado)
            await self.repo.delete(id)
            await self.gov_repo.create_audit_log(
                "DELETE", "INV_ADJUNTO",
                {"id": str(id), "nombre": adjunto.ADJ_Nombre_Original},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            _safe_remove(abs_path)
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")


def _safe_remove(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
