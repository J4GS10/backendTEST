"""Servicio de Software/Licencias/Instalaciones."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import internal_error
from app.core.security import encrypt_field, decrypt_field
from app.models.software import Software as SoftwareModel
from app.repositories.governance import GovernanceRepository
from app.repositories.software import SoftwareRepository
from app.schemas.software import (
    InstalacionCreate,
    LicenciaCreate,
    LicenciaUpdate,
    SoftwareCreate,
    SoftwareUpdate,
    TipoLicenciaCreate,
    TipoLicenciaUpdate,
)


class SoftwareService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SoftwareRepository(db)
        self.gov_repo = GovernanceRepository(db)

    # =====================================================================
    # TIPO LICENCIA
    # =====================================================================
    async def create_tipo_licencia(self, schema: TipoLicenciaCreate, usuario_id=None, ip=None):
        try:
            obj = await self.repo.create_tipo_licencia(schema)
            await self.gov_repo.create_audit_log(
                "CREATE", "INV_TIPO_LICENCIA", {"nombre": schema.TLI_Nombre},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            await self.db.refresh(obj)
            return obj
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def list_tipos_licencia(self):
        return await self.repo.get_tipos_licencia()

    async def update_tipo_licencia(self, id: int, schema: TipoLicenciaUpdate, usuario_id=None, ip=None):
        try:
            tipo = await self.repo.get_tipo_licencia_by_id(id)
            if not tipo:
                raise HTTPException(404, detail="LICENSE_TYPE_NOT_FOUND")
            obj = await self.repo.update_tipo_licencia(id, schema)
            await self.gov_repo.create_audit_log(
                "UPDATE", "INV_TIPO_LICENCIA",
                {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            return obj
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def delete_tipo_licencia(self, id: int, usuario_id=None, ip=None):
        try:
            tipo = await self.repo.get_tipo_licencia_by_id(id)
            if not tipo:
                raise HTTPException(404, detail="LICENSE_TYPE_NOT_FOUND")
            count = await self.repo.count_licencias_by_tipo(id)
            if count > 0:
                raise HTTPException(409, detail="CANNOT_DELETE_TYPE_HAS_LICENSES")
            await self.repo.delete_tipo_licencia(id)
            await self.gov_repo.create_audit_log(
                "DELETE", "INV_TIPO_LICENCIA",
                {"id": id, "nombre": tipo.TLI_Nombre},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    # =====================================================================
    # SOFTWARE
    # =====================================================================
    async def create_software(self, schema: SoftwareCreate, usuario_id=None, ip=None):
        try:
            obj = await self.repo.create_software(schema)
            await self.gov_repo.create_audit_log(
                "CREATE", "INV_SOFTWARE",
                {"nombre": schema.SOF_Nombre, "version": schema.SOF_Version},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            await self.db.refresh(obj)
            return obj
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def list_software(self):
        return await self.repo.get_software_all()

    async def update_software(self, id: int, schema: SoftwareUpdate, usuario_id=None, ip=None):
        try:
            sw = await self.repo.get_software_by_id(id)
            if not sw:
                raise HTTPException(404, detail="SOFTWARE_NOT_FOUND")
            obj = await self.repo.update_software(id, schema)
            await self.gov_repo.create_audit_log(
                "UPDATE", "INV_SOFTWARE",
                {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            return obj
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def delete_software(self, id: int, usuario_id=None, ip=None):
        try:
            sw = await self.repo.get_software_by_id(id)
            if not sw:
                raise HTTPException(404, detail="SOFTWARE_NOT_FOUND")
            count = await self.repo.count_licencias_by_software(id)
            if count > 0:
                raise HTTPException(409, detail="CANNOT_DELETE_SOFTWARE_HAS_LICENSES")
            await self.repo.delete_software(id)
            await self.gov_repo.create_audit_log(
                "DELETE", "INV_SOFTWARE",
                {"id": id, "nombre": sw.SOF_Nombre},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    # =====================================================================
    # LICENCIAS
    # =====================================================================
    async def create_licencia(self, schema: LicenciaCreate, usuario_id=None, ip=None):
        try:
            sw = await self.db.execute(
                select(SoftwareModel).where(SoftwareModel.SOF_Software == schema.SOF_Software)
            )
            if not sw.scalar_one_or_none():
                raise HTTPException(404, detail="SOFTWARE_NOT_FOUND")

            # Validar fecha de vencimiento.
            if schema.LIC_Fecha_Vencimiento and schema.LIC_Fecha_Vencimiento < date.today():
                raise HTTPException(400, detail="LICENSE_EXPIRATION_IN_THE_PAST")

            # Cifrar clave de activación si viene.
            payload = schema.model_copy(update={
                "LIC_Clave_Activacion": encrypt_field(schema.LIC_Clave_Activacion)
            })
            obj = await self.repo.create_licencia(payload)

            await self.gov_repo.create_audit_log(
                "CREATE", "INV_LICENCIA",
                {"software_id": schema.SOF_Software, "cantidad_total": schema.LIC_Cantidad_Total},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            await self.db.refresh(obj)
            return obj
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def list_licencias(self, software_id: int):
        items = await self.repo.get_licencias_by_software(software_id)
        for it in items:
            it.LIC_Clave_Activacion = decrypt_field(it.LIC_Clave_Activacion)
        return items

    async def get_licencia(self, id: int):
        obj = await self.repo.get_licencia_by_id(id)
        if not obj:
            raise HTTPException(404, "LICENSE_NOT_FOUND")
        obj.LIC_Clave_Activacion = decrypt_field(obj.LIC_Clave_Activacion)
        return obj

    async def update_licencia(self, id: int, schema: LicenciaUpdate, usuario_id=None, ip=None):
        obj = await self.repo.get_licencia_by_id(id)
        if not obj:
            raise HTTPException(404, "LICENSE_NOT_FOUND")

        # Validar que LIC_Cantidad_Total no quede por debajo del uso actual
        if schema.LIC_Cantidad_Total is not None and schema.LIC_Cantidad_Total < obj.LIC_Cantidad_Usada:
            raise HTTPException(
                400, f"CANNOT_REDUCE_BELOW_USED:{obj.LIC_Cantidad_Usada}"
            )

        # Cifrar clave si viene
        data = schema.model_copy()
        if data.LIC_Clave_Activacion is not None:
            data = data.model_copy(update={"LIC_Clave_Activacion": encrypt_field(data.LIC_Clave_Activacion)})

        updated = await self.repo.update_licencia(id, data)
        await self.gov_repo.create_audit_log(
            "UPDATE", "INV_LICENCIA",
            {"id": id, "cambios": schema.model_dump(exclude_unset=True, exclude={"LIC_Clave_Activacion"})},
            usuario_id=usuario_id, ip_origen=ip,
        )
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback(); raise
        return updated

    async def delete_licencia(self, id: int, usuario_id=None, ip=None):
        obj = await self.repo.get_licencia_by_id(id)
        if not obj:
            raise HTTPException(404, "LICENSE_NOT_FOUND")

        # Si hay instalaciones activas, no se puede eliminar
        activas = await self.repo.count_instalaciones_activas_de_licencia(id)
        if activas > 0:
            raise HTTPException(409, f"CANNOT_DELETE_LICENSE_WITH_ACTIVE_INSTALLATIONS:{activas}")

        try:
            await self.repo.delete_licencia(id)
            await self.gov_repo.create_audit_log(
                "DELETE", "INV_LICENCIA",
                {"id": id, "software_id": obj.SOF_Software, "total": obj.LIC_Cantidad_Total},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
        except HTTPException:
            await self.db.rollback(); raise
        except Exception:
            await self.db.rollback()
            raise HTTPException(409, "CANNOT_DELETE_LICENSE_IN_USE")

    async def list_instalaciones_by_activo(self, activo_id: uuid.UUID, solo_activas: bool = True):
        """Lista las instalaciones (con software/tipo_licencia poblados) de un activo."""
        return await self.repo.get_instalaciones_by_activo(activo_id, solo_activas=solo_activas)

    # =====================================================================
    # INSTALACIONES — Operación ACID con UPDATE atómico
    # =====================================================================
    async def registrar_instalacion(
        self,
        schema: InstalacionCreate,
        usuario_id: uuid.UUID | None = None,
        ip: str | None = None,
    ):
        """
        Flujo:
        1. Reservar cupo de licencia con UPDATE atómico condicional.
           Si no hay cupos, 409 directo (sin race condition).
        2. Validar duplicidad (no instalada ya).
        3. Crear Instalacion.
        4. Auditoría.
        5. Commit.
        """
        try:
            existe = await self.repo.get_instalacion_activa(schema.ACT_Activo, schema.LIC_Licencia)
            if existe:
                raise HTTPException(400, detail="LICENSE_ALREADY_INSTALLED_ON_ASSET")

            reservado = await self.repo.reservar_cupo_licencia(schema.LIC_Licencia)
            if not reservado:
                # No hay cupos o no existe la licencia.
                licencia = await self.repo.get_licencia_by_id(schema.LIC_Licencia)
                if not licencia:
                    raise HTTPException(404, detail="LICENSE_NOT_FOUND")
                raise HTTPException(409, detail="NO_LICENSE_SEATS_AVAILABLE")

            instalacion = await self.repo.create_instalacion(schema)

            await self.gov_repo.create_audit_log(
                "INSTALL", "INV_INSTALACION",
                {"activo": str(schema.ACT_Activo), "licencia": schema.LIC_Licencia},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            await self.db.refresh(instalacion)
            return instalacion
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def desinstalar_software(
        self,
        schema: InstalacionCreate,
        usuario_id: uuid.UUID | None = None,
        ip: str | None = None,
    ):
        """
        UPDATE condicional para que doble-desinstalación no decremente dos veces.
        """
        try:
            desactivado = await self.repo.desactivar_instalacion_atomico(
                schema.ACT_Activo, schema.LIC_Licencia
            )
            if not desactivado:
                raise HTTPException(404, detail="INSTALLATION_NOT_FOUND_OR_ALREADY_REMOVED")

            liberado = await self.repo.liberar_cupo_licencia(schema.LIC_Licencia)
            if not liberado:
                # Inconsistencia ya existente: cupo ya estaba en 0. Loggear pero no romper.
                pass

            await self.gov_repo.create_audit_log(
                "UNINSTALL", "INV_INSTALACION",
                {"activo": str(schema.ACT_Activo), "licencia": schema.LIC_Licencia},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            return {"status": "success", "message": "SOFTWARE_UNINSTALLED_SUCCESSFULLY"}
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")
