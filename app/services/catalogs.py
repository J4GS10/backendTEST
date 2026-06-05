"""Servicio de catálogos técnicos. Con auditoría + transacciones."""
from __future__ import annotations

import uuid
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.transactional import commit_or_409
from app.repositories.catalogs import CatalogRepository
from app.repositories.governance import GovernanceRepository
from app.schemas.catalogs import (
    EstadoOperativoCreate, EstadoOperativoUpdate,
    MarcaCreate, MarcaUpdate,
    ModeloCreate, ModeloUpdate,
    TipoActivoCreate, TipoActivoUpdate,
    TipoConexionCreate, TipoConexionUpdate,
    TipoEspecificacionCreate, TipoEspecificacionUpdate,
)


def _audit_ctx(usuario_id, ip):
    return {"usuario_id": usuario_id, "ip_origen": ip}


# Estados operativos de los que depende la máquina de estados de los activos
# (ver services/traceability.py y services/maintenance.py). Sus filas son "del
# sistema": no se pueden renombrar ni borrar vía la API de catálogos.
_PROTECTED_ESTADO_NAMES = frozenset(
    {"disponible", "asignado", "en reparación", "en reparacion", "baja", "en bodega"}
)


class CatalogService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CatalogRepository(db)
        self.gov_repo = GovernanceRepository(db)

    async def _commit_or_rollback(self):
        await commit_or_409(self.db, where="CatalogService")

    # =====================================================================
    # TIPO DE ACTIVO
    # =====================================================================
    async def create_tipo_activo(self, schema: TipoActivoCreate, usuario_id=None, ip=None):
        if await self.repo.get_tipo_activo_by_name(schema.TAC_Nombre):
            raise HTTPException(400, "ASSET_TYPE_ALREADY_EXISTS")
        obj = await self.repo.create_tipo_activo(schema)
        await self.gov_repo.create_audit_log(
            "CREATE", "INV_TIPO_ACTIVO", {"nombre": schema.TAC_Nombre}, **_audit_ctx(usuario_id, ip)
        )
        await self._commit_or_rollback()
        return obj

    async def list_tipos_activo(self):
        return await self.repo.get_tipos_activo()

    async def get_tipo_activo(self, id: int):
        obj = await self.repo.get_tipo_activo_by_id(id)
        if not obj:
            raise HTTPException(404, "ASSET_TYPE_NOT_FOUND")
        return obj

    async def update_tipo_activo(self, id: int, schema: TipoActivoUpdate, usuario_id=None, ip=None):
        if not await self.repo.get_tipo_activo_by_id(id):
            raise HTTPException(404, "ASSET_TYPE_NOT_FOUND")
        obj = await self.repo.update_tipo_activo(id, schema)
        await self.gov_repo.create_audit_log(
            "UPDATE", "INV_TIPO_ACTIVO",
            {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            **_audit_ctx(usuario_id, ip),
        )
        await self._commit_or_rollback()
        return obj

    async def delete_tipo_activo(self, id: int, usuario_id=None, ip=None):
        obj = await self.repo.get_tipo_activo_by_id(id)
        if not obj:
            raise HTTPException(404, "ASSET_TYPE_NOT_FOUND")
        try:
            await self.repo.delete_tipo_activo(id)
            await self.gov_repo.create_audit_log(
                "DELETE", "INV_TIPO_ACTIVO",
                {"id": id, "nombre": obj.TAC_Nombre},
                **_audit_ctx(usuario_id, ip),
            )
            await self._commit_or_rollback()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(409, "CANNOT_DELETE_ASSET_TYPE_IN_USE")

    # =====================================================================
    # MARCA
    # =====================================================================
    async def create_marca(self, schema: MarcaCreate, usuario_id=None, ip=None):
        if await self.repo.get_marca_by_name(schema.MAR_Nombre):
            raise HTTPException(400, "BRAND_ALREADY_EXISTS")
        obj = await self.repo.create_marca(schema)
        await self.gov_repo.create_audit_log(
            "CREATE", "INV_MARCA", {"nombre": schema.MAR_Nombre}, **_audit_ctx(usuario_id, ip)
        )
        await self._commit_or_rollback()
        return obj

    async def list_marcas(self):
        return await self.repo.get_marcas()

    async def get_marca(self, id: int):
        obj = await self.repo.get_marca_by_id(id)
        if not obj:
            raise HTTPException(404, "BRAND_NOT_FOUND")
        return obj

    async def update_marca(self, id: int, schema: MarcaUpdate, usuario_id=None, ip=None):
        if not await self.repo.get_marca_by_id(id):
            raise HTTPException(404, "BRAND_NOT_FOUND")
        obj = await self.repo.update_marca(id, schema)
        await self.gov_repo.create_audit_log(
            "UPDATE", "INV_MARCA",
            {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            **_audit_ctx(usuario_id, ip),
        )
        await self._commit_or_rollback()
        return obj

    async def delete_marca(self, id: int, usuario_id=None, ip=None):
        obj = await self.repo.get_marca_by_id(id)
        if not obj:
            raise HTTPException(404, "BRAND_NOT_FOUND")
        try:
            await self.repo.delete_marca(id)
            await self.gov_repo.create_audit_log(
                "DELETE", "INV_MARCA", {"id": id, "nombre": obj.MAR_Nombre},
                **_audit_ctx(usuario_id, ip),
            )
            await self._commit_or_rollback()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(409, "CANNOT_DELETE_BRAND_IN_USE")

    # =====================================================================
    # TIPO DE CONEXIÓN
    # =====================================================================
    async def create_tipo_conexion(self, schema: TipoConexionCreate, usuario_id=None, ip=None):
        obj = await self.repo.create_tipo_conexion(schema)
        await self.gov_repo.create_audit_log(
            "CREATE", "INV_TIPO_CONEXION", {"nombre": schema.TCN_Nombre},
            **_audit_ctx(usuario_id, ip),
        )
        await self._commit_or_rollback()
        return obj

    async def list_tipos_conexion(self):
        return await self.repo.get_tipos_conexion()

    async def get_tipo_conexion(self, id: int):
        obj = await self.repo.get_tipo_conexion_by_id(id)
        if not obj:
            raise HTTPException(404, "CONNECTION_TYPE_NOT_FOUND")
        return obj

    async def update_tipo_conexion(self, id: int, schema: TipoConexionUpdate, usuario_id=None, ip=None):
        if not await self.repo.get_tipo_conexion_by_id(id):
            raise HTTPException(404, "CONNECTION_TYPE_NOT_FOUND")
        obj = await self.repo.update_tipo_conexion(id, schema)
        await self.gov_repo.create_audit_log(
            "UPDATE", "INV_TIPO_CONEXION",
            {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            **_audit_ctx(usuario_id, ip),
        )
        await self._commit_or_rollback()
        return obj

    async def delete_tipo_conexion(self, id: int, usuario_id=None, ip=None):
        obj = await self.repo.get_tipo_conexion_by_id(id)
        if not obj:
            raise HTTPException(404, "CONNECTION_TYPE_NOT_FOUND")
        try:
            await self.repo.delete_tipo_conexion(id)
            await self.gov_repo.create_audit_log(
                "DELETE", "INV_TIPO_CONEXION", {"id": id, "nombre": obj.TCN_Nombre},
                **_audit_ctx(usuario_id, ip),
            )
            await self._commit_or_rollback()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(409, "CANNOT_DELETE_CONNECTION_TYPE_IN_USE")

    # =====================================================================
    # MODELO
    # =====================================================================
    async def create_modelo(self, schema: ModeloCreate, usuario_id=None, ip=None):
        obj = await self.repo.create_modelo(schema)
        await self.gov_repo.create_audit_log(
            "CREATE", "INV_MODELO",
            {"nombre": schema.MOD_Nombre, "marca_id": schema.MAR_Marca},
            **_audit_ctx(usuario_id, ip),
        )
        await self._commit_or_rollback()
        return obj

    async def list_modelos(self, marca_id: int, tipo_id: int | None = None):
        return await self.repo.get_modelos_by_marca(marca_id, tipo_id=tipo_id)

    async def list_modelos_flat(self, q: str | None = None, limit: int = 500, tipo_id: int | None = None):
        return await self.repo.get_modelos_flat(q=q, limit=limit, tipo_id=tipo_id)

    async def get_modelo(self, id: int):
        obj = await self.repo.get_modelo_by_id(id)
        if not obj:
            raise HTTPException(404, "MODEL_NOT_FOUND")
        return obj

    async def update_modelo(self, id: int, schema: ModeloUpdate, usuario_id=None, ip=None):
        if not await self.repo.get_modelo_by_id(id):
            raise HTTPException(404, "MODEL_NOT_FOUND")
        obj = await self.repo.update_modelo(id, schema)
        await self.gov_repo.create_audit_log(
            "UPDATE", "INV_MODELO",
            {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            **_audit_ctx(usuario_id, ip),
        )
        await self._commit_or_rollback()
        return obj

    async def delete_modelo(self, id: int, usuario_id=None, ip=None):
        obj = await self.repo.get_modelo_by_id(id)
        if not obj:
            raise HTTPException(404, "MODEL_NOT_FOUND")
        try:
            await self.repo.delete_modelo(id)
            await self.gov_repo.create_audit_log(
                "DELETE", "INV_MODELO", {"id": id, "nombre": obj.MOD_Nombre},
                **_audit_ctx(usuario_id, ip),
            )
            await self._commit_or_rollback()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(409, "CANNOT_DELETE_MODEL_IN_USE")

    # =====================================================================
    # ESTADO OPERATIVO
    # =====================================================================
    async def create_estado_operativo(self, schema: EstadoOperativoCreate, usuario_id=None, ip=None):
        obj = await self.repo.create_estado_operativo(schema)
        await self.gov_repo.create_audit_log(
            "CREATE", "INV_ESTADO_OPERATIVO", {"nombre": schema.EOP_Nombre},
            **_audit_ctx(usuario_id, ip),
        )
        await self._commit_or_rollback()
        return obj

    async def list_estados_operativos(self):
        return await self.repo.get_estados_operativos()

    async def get_estado_operativo(self, id: int):
        obj = await self.repo.get_estado_operativo_by_id(id)
        if not obj:
            raise HTTPException(404, "OPERATIONAL_STATUS_NOT_FOUND")
        return obj

    async def update_estado_operativo(self, id: int, schema: EstadoOperativoUpdate, usuario_id=None, ip=None):
        existing = await self.repo.get_estado_operativo_by_id(id)
        if not existing:
            raise HTTPException(404, "OPERATIONAL_STATUS_NOT_FOUND")
        # Las transiciones de estado dependen de estos nombres canónicos: no se
        # pueden renombrar (rompería la máquina de estados de los activos).
        if (existing.EOP_Nombre or "").strip().lower() in _PROTECTED_ESTADO_NAMES:
            raise HTTPException(409, "CANNOT_MODIFY_SYSTEM_OPERATIONAL_STATUS")
        obj = await self.repo.update_estado_operativo(id, schema)
        await self.gov_repo.create_audit_log(
            "UPDATE", "INV_ESTADO_OPERATIVO",
            {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            **_audit_ctx(usuario_id, ip),
        )
        await self._commit_or_rollback()
        return obj

    async def delete_estado_operativo(self, id: int, usuario_id=None, ip=None):
        obj = await self.repo.get_estado_operativo_by_id(id)
        if not obj:
            raise HTTPException(404, "OPERATIONAL_STATUS_NOT_FOUND")
        if (obj.EOP_Nombre or "").strip().lower() in _PROTECTED_ESTADO_NAMES:
            raise HTTPException(409, "CANNOT_DELETE_SYSTEM_OPERATIONAL_STATUS")
        try:
            await self.repo.delete_estado_operativo(id)
            await self.gov_repo.create_audit_log(
                "DELETE", "INV_ESTADO_OPERATIVO", {"id": id, "nombre": obj.EOP_Nombre},
                **_audit_ctx(usuario_id, ip),
            )
            await self._commit_or_rollback()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(409, "CANNOT_DELETE_OPERATIONAL_STATUS_IN_USE")

    # =====================================================================
    # TIPO DE ESPECIFICACIÓN
    # =====================================================================
    async def create_tipo_especificacion(self, schema: TipoEspecificacionCreate, usuario_id=None, ip=None):
        obj = await self.repo.create_tipo_especificacion(schema)
        await self.gov_repo.create_audit_log(
            "CREATE", "INV_TIPO_ESPECIFICACION", {"nombre": schema.TES_Nombre},
            **_audit_ctx(usuario_id, ip),
        )
        await self._commit_or_rollback()
        return obj

    async def list_tipos_especificacion(self):
        return await self.repo.get_tipos_especificacion()

    async def get_tipo_especificacion(self, id: int):
        obj = await self.repo.get_tipo_especificacion_by_id(id)
        if not obj:
            raise HTTPException(404, "SPECIFICATION_TYPE_NOT_FOUND")
        return obj

    async def update_tipo_especificacion(self, id: int, schema: TipoEspecificacionUpdate, usuario_id=None, ip=None):
        if not await self.repo.get_tipo_especificacion_by_id(id):
            raise HTTPException(404, "SPECIFICATION_TYPE_NOT_FOUND")
        obj = await self.repo.update_tipo_especificacion(id, schema)
        await self.gov_repo.create_audit_log(
            "UPDATE", "INV_TIPO_ESPECIFICACION",
            {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            **_audit_ctx(usuario_id, ip),
        )
        await self._commit_or_rollback()
        return obj

    async def delete_tipo_especificacion(self, id: int, usuario_id=None, ip=None):
        obj = await self.repo.get_tipo_especificacion_by_id(id)
        if not obj:
            raise HTTPException(404, "SPECIFICATION_TYPE_NOT_FOUND")
        try:
            await self.repo.delete_tipo_especificacion(id)
            await self.gov_repo.create_audit_log(
                "DELETE", "INV_TIPO_ESPECIFICACION", {"id": id, "nombre": obj.TES_Nombre},
                **_audit_ctx(usuario_id, ip),
            )
            await self._commit_or_rollback()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(409, "CANNOT_DELETE_SPECIFICATION_TYPE_IN_USE")
