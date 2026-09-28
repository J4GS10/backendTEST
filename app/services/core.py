from __future__ import annotations

from fastapi import HTTPException, status
from app.core.transactional import transactional
from app.services.notification import NotificationService
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import uuid
from datetime import datetime, timezone

from app.core.data_scope import elevated, require_sede
from app.services.base import BaseService
from app.repositories.core import CoreRepository
from app.repositories.catalogs import CatalogRepository
from app.repositories.governance import GovernanceRepository
from app.repositories.traceability import TraceabilityRepository

from app.models.organization import Persona, Usuario
from app.models.traceability import Movimiento
from app.models.catalogs import EstadoOperativo

from app.schemas.core import ActivoCreate, ActivoUpdate, ActivoFilter


class CoreService(BaseService[CoreRepository]):
    repo_class = CoreRepository

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.cat_repo = CatalogRepository(db)
        self.gov_repo = GovernanceRepository(db)
        self.trace_repo = TraceabilityRepository(db)

    # =================================================================
    # CREATE — ACID con auditoría
    # =================================================================
    @transactional
    async def create_activo(self, schema: ActivoCreate, usuario_id: uuid.UUID | None = None):
        # 1. VALIDACIONES DE FK
        tipo_activo = await self.cat_repo.get_tipo_activo_by_id(schema.TAC_Tipo_Activo)
        if not tipo_activo:
            raise HTTPException(status_code=404, detail="ASSET_TYPE_NOT_FOUND")

        modelo = await self.cat_repo.get_modelo_by_id(schema.MOD_Modelo)
        if not modelo:
            raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")

        estado = await self.cat_repo.get_estado_operativo_by_id(schema.EOP_Estado_Operativo)
        if not estado:
            raise HTTPException(status_code=404, detail="OPERATIONAL_STATUS_NOT_FOUND")

        # Sede dentro del alcance del usuario (su única sede si no la indica).
        schema.SED_Sede = require_sede(schema.SED_Sede, required=False)
        if schema.ACT_Activo_Padre and not await self.repo.get_by_id_simple(schema.ACT_Activo_Padre):
            raise HTTPException(status_code=404, detail="PARENT_ASSET_NOT_FOUND")

        # 2. LÓGICA DE SECUENCIAS (Código Interno automático)
        if not schema.ACT_Codigo_Interno:
            if not tipo_activo.TAC_Prefijo:
                raise HTTPException(
                    status_code=400,
                    detail="ASSET_TYPE_HAS_NO_PREFIX_CONFIGURED_FOR_AUTO_GENERATION"
                )
            contexto_secuencia = f"ASSET_{tipo_activo.TAC_Prefijo}"
            nuevo_codigo = await self.gov_repo.get_next_code(
                contexto=contexto_secuencia,
                prefijo=tipo_activo.TAC_Prefijo
            )
            schema.ACT_Codigo_Interno = nuevo_codigo

        # 3. VALIDACIONES DE UNICIDAD (en toda la empresa, no solo en el alcance)
        async with elevated(self.db):
            codigo_existe = await self.repo.get_by_codigo_interno(schema.ACT_Codigo_Interno)
            serie_existe = await self.repo.get_by_serie(schema.ACT_Serie_Fabricante)
        if codigo_existe:
            raise HTTPException(status_code=400, detail="ASSET_CODE_ALREADY_EXISTS")
        if serie_existe:
            raise HTTPException(status_code=400, detail="SERIAL_NUMBER_ALREADY_EXISTS")

        # 4. VALIDACIÓN DE NEGOCIO: Garantía >= Fecha Compra
        if schema.ACT_Fin_Garantia and schema.ACT_Fin_Garantia < schema.ACT_Fecha_Compra:
            raise HTTPException(
                status_code=400,
                detail="WARRANTY_DATE_CANNOT_BE_BEFORE_PURCHASE_DATE"
            )

        # 5. CREACIÓN
        nuevo_activo = await self.repo.create_activo(schema)

        # Nota: no creamos un movimiento "automático" de ingreso. El alta
        # del activo NO implica asignación. Si se desea registrar quién
        # recibe el activo en bodega, se hace explícitamente con
        # POST /trazabilidad/movimientos.

        # 7. AUDITORÍA
        await self.gov_repo.create_audit_log(
            accion="CREATE",
            entidad="INV_ACTIVO",
            snapshot={"codigo": schema.ACT_Codigo_Interno, "serie": schema.ACT_Serie_Fabricante,
                      "sede": schema.SED_Sede},
            usuario_id=usuario_id, sede_id=schema.SED_Sede,
        )

        # 8. COMMIT ATÓMICO
        return nuevo_activo

    # =================================================================
    # UPDATE — Con validaciones de colisión
    # =================================================================
    @transactional
    async def update_activo(self, activo_id: uuid.UUID, schema: ActivoUpdate, usuario_id: uuid.UUID | None = None):
        activo_actual = await self.get_or_404(activo_id, "ASSET")

        # Validar FK de Modelo si se envía
        if schema.MOD_Modelo is not None:
            modelo = await self.cat_repo.get_modelo_by_id(schema.MOD_Modelo)
            if not modelo:
                raise HTTPException(status_code=404, detail="MODEL_NOT_FOUND")

        # Validar FK de Estado Operativo si se envía
        if schema.EOP_Estado_Operativo is not None:
            estado = await self.cat_repo.get_estado_operativo_by_id(schema.EOP_Estado_Operativo)
            if not estado:
                raise HTTPException(status_code=404, detail="OPERATIONAL_STATUS_NOT_FOUND")

        # Cambio de sede: debe quedar en el alcance y el activo no puede estar
        # asignado (mientras lo está, su sede es la del área de la asignación).
        sede_final = activo_actual.SED_Sede
        if "SED_Sede" in schema.model_fields_set and schema.SED_Sede != activo_actual.SED_Sede:
            schema.SED_Sede = require_sede(schema.SED_Sede, required=False)
            if await self.trace_repo.get_movimiento_vigente(activo_id):
                raise HTTPException(status_code=400, detail="CANNOT_CHANGE_SEDE_OF_ASSIGNED_ASSET")
            sede_final = schema.SED_Sede

        # Validar colisión de Código
        if schema.ACT_Codigo_Interno and schema.ACT_Codigo_Interno != activo_actual.ACT_Codigo_Interno:
            async with elevated(self.db):
                existe = await self.repo.get_by_codigo_interno(schema.ACT_Codigo_Interno)
            if existe:
                raise HTTPException(status_code=400, detail="NEW_ASSET_CODE_ALREADY_EXISTS")

        # Validar colisión de Serie
        if schema.ACT_Serie_Fabricante and schema.ACT_Serie_Fabricante != activo_actual.ACT_Serie_Fabricante:
            async with elevated(self.db):
                existe = await self.repo.get_by_serie(schema.ACT_Serie_Fabricante)
            if existe:
                raise HTTPException(status_code=400, detail="NEW_SERIAL_NUMBER_ALREADY_EXISTS")

        resultado = await self.repo.update_activo(activo_id, schema)

        # Auditoría
        await self.gov_repo.create_audit_log(
            accion="UPDATE",
            entidad="INV_ACTIVO",
            snapshot={"activo_id": str(activo_id), "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, sede_id=sede_final,
        )
        return resultado

    # =================================================================
    # READ
    # =================================================================
    async def list_activos(self, skip: int, limit: int):
        return await self.repo.get_all(skip, limit)

    async def get_activo_detail(self, activo_id: uuid.UUID):
        return await self.get_or_404(activo_id, "ASSET")

    async def get_activo_by_codigo(self, codigo: str):
        activo = await self.repo.get_by_codigo_interno(codigo.strip())
        if not activo:
            raise HTTPException(status_code=404, detail="ASSET_NOT_FOUND")
        return await self.repo.get_by_id(activo.ACT_Activo)

    async def search_activos(self, filters: ActivoFilter):
        return await self.repo.search_activos(filters)

    # =================================================================
    # DELETE (Baja Lógica) — ACID con validaciones
    # =================================================================
    @transactional
    async def delete_activo(self, activo_id: uuid.UUID, usuario_id: uuid.UUID | None = None):
        activo = await self.repo.get_by_id_simple(activo_id)
        if not activo:
            raise HTTPException(status_code=404, detail="ASSET_NOT_FOUND")

        # Verificar que NO esté asignado actualmente
        q_check = select(Movimiento).where(
            Movimiento.ACT_Activo == activo_id,
            Movimiento.MOV_Fecha_Devolucion == None
        )
        res_check = await self.db.execute(q_check)
        if res_check.first():
            raise HTTPException(
                status_code=400,
                detail="CANNOT_DELETE_ASSIGNED_ASSET_RETURN_IT_FIRST"
            )

        # Buscar Estado "BAJA"
        q_estado = select(EstadoOperativo).where(EstadoOperativo.EOP_Nombre.ilike("Baja"))
        res_estado = await self.db.execute(q_estado)
        estado_baja = res_estado.scalar_one_or_none()

        if not estado_baja:
            raise HTTPException(
                status_code=500,
                detail="SYSTEM_CONFIGURATION_ERROR_MISSING_STATUS_BAJA"
            )

        # Soft Delete
        update_schema = ActivoUpdate(EOP_Estado_Operativo=estado_baja.EOP_Estado_Operativo)
        resultado = await self.repo.update_activo(activo_id, update_schema)

        # Auditoría
        await self.gov_repo.create_audit_log(
            accion="DELETE_LOGIC",
            entidad="INV_ACTIVO",
            snapshot={"activo_id": str(activo_id), "codigo": activo.ACT_Codigo_Interno},
            usuario_id=usuario_id, sede_id=activo.SED_Sede,
        )

        # Resolver info del operador dentro de la transacción activa.
        op_name, op_role, op_email = await self._operator_info(usuario_id)

        NotificationService.schedule_baja(
            activo_codigo=activo.ACT_Codigo_Interno,
            activo_serie=activo.ACT_Serie_Fabricante,
            fecha_iso=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            operador_nombre=op_name,
            operador_email=op_email,
            operador_rol=op_role,
        )
        return resultado

    # =================================================================
    # HELPERS PRIVADOS
    # =================================================================
    async def _operator_info(self, usuario_id: uuid.UUID | None) -> tuple[str, str, str | None]:
        """Resuelve (nombre_completo, rol, email) del operador para notificaciones."""
        if not usuario_id:
            return ("Sistema", "", None)
        row = (await self.db.execute(
            select(
                Usuario.USU_Username, Usuario.USU_Rol,
                Persona.PER_Primer_Nombre, Persona.PER_Primer_Apellido,
                Persona.PER_Email_Corporativo,
            )
            .join(Persona, Persona.PER_Persona == Usuario.PER_Persona, isouter=True)
            .where(Usuario.USU_Usuario == usuario_id)
        )).first()
        if not row:
            return ("Sistema", "", None)
        username, rol, nombre, apellido, email = row
        if nombre:
            return (f"{nombre} {apellido}", rol or "", email)
        return (username, rol or "", None)

    # =================================================================
    # ESPECIFICACIONES (características del equipo: RAM, disco, batería…)
    # =================================================================
    async def list_especificaciones(self, activo_id: uuid.UUID):
        if not await self.repo.get_by_id_simple(activo_id):
            raise HTTPException(404, "ASSET_NOT_FOUND")
        return await self.repo.list_especificaciones(activo_id)

    @transactional
    async def add_especificacion(self, activo_id, tes_id, valor, usuario_id=None, ip=None):
        activo = await self.repo.get_by_id_simple(activo_id)
        if not activo:
            raise HTTPException(404, "ASSET_NOT_FOUND")
        if not await self.cat_repo.get_tipo_especificacion_by_id(tes_id):
            raise HTTPException(404, "SPECIFICATION_TYPE_NOT_FOUND")
        obj = await self.repo.add_especificacion(activo_id, tes_id, valor)
        await self.gov_repo.create_audit_log(
            "CREATE", "INV_ESPECIFICACION",
            {"activo": str(activo_id), "tipo": tes_id, "valor": valor[:120]},
            usuario_id=usuario_id, ip_origen=ip, sede_id=activo.SED_Sede,
        )
        return obj

    @transactional
    async def update_especificacion(self, esp_id, valor, usuario_id=None, ip=None):
        if not await self.repo.get_especificacion(esp_id):
            raise HTTPException(404, "SPECIFICATION_NOT_FOUND")
        await self.repo.update_especificacion(esp_id, valor)
        await self.gov_repo.create_audit_log(
            "UPDATE", "INV_ESPECIFICACION", {"id": esp_id, "valor": valor[:120]},
            usuario_id=usuario_id, ip_origen=ip,
        )

    @transactional
    async def delete_especificacion(self, esp_id, usuario_id=None, ip=None):
        obj = await self.repo.get_especificacion(esp_id)
        if not obj:
            raise HTTPException(404, "SPECIFICATION_NOT_FOUND")
        await self.repo.delete_especificacion(esp_id)
        await self.gov_repo.create_audit_log(
            "DELETE", "INV_ESPECIFICACION", {"id": esp_id},
            usuario_id=usuario_id, ip_origen=ip,
        )
