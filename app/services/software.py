"""Servicio de Software/Licencias/Instalaciones."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt_field, decrypt_field, fingerprint_field
from app.core.transactional import transactional
from app.models.core import Activo
from app.models.organization import Persona
from app.models.software import Software as SoftwareModel
from app.repositories.governance import GovernanceRepository
from app.repositories.software import SoftwareRepository
from app.services.base import BaseService
from app.schemas.software import (
    InstalacionCreate,
    LicenciaCreate,
    LicenciaClaveCreate,
    LicenciaClaveResponse,
    LicenciaUpdate,
    SoftwareCreate,
    SoftwareUpdate,
    TipoLicenciaCreate,
    TipoLicenciaUpdate,
)


class SoftwareService(BaseService[SoftwareRepository]):
    repo_class = SoftwareRepository

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.gov_repo = GovernanceRepository(db)

    # =====================================================================
    # TIPO LICENCIA
    # =====================================================================
    @transactional
    async def create_tipo_licencia(self, schema: TipoLicenciaCreate, usuario_id=None, ip=None):
        obj = await self.repo.create_tipo_licencia(schema)
        await self.gov_repo.create_audit_log(
            "CREATE", "INV_TIPO_LICENCIA", {"nombre": schema.TLI_Nombre},
            usuario_id=usuario_id, ip_origen=ip,
        )
        return obj

    async def list_tipos_licencia(self):
        return await self.repo.get_tipos_licencia()

    @transactional
    async def update_tipo_licencia(self, id: int, schema: TipoLicenciaUpdate, usuario_id=None, ip=None):
        tipo = await self.repo.get_tipo_licencia_by_id(id)
        if not tipo:
            raise HTTPException(404, detail="LICENSE_TYPE_NOT_FOUND")
        obj = await self.repo.update_tipo_licencia(id, schema)
        await self.gov_repo.create_audit_log(
            "UPDATE", "INV_TIPO_LICENCIA",
            {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip_origen=ip,
        )
        return obj

    @transactional
    async def delete_tipo_licencia(self, id: int, usuario_id=None, ip=None):
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

    # =====================================================================
    # SOFTWARE
    # =====================================================================
    @transactional
    async def create_software(self, schema: SoftwareCreate, usuario_id=None, ip=None):
        obj = await self.repo.create_software(schema)
        await self.gov_repo.create_audit_log(
            "CREATE", "INV_SOFTWARE",
            {"nombre": schema.SOF_Nombre, "version": schema.SOF_Version},
            usuario_id=usuario_id, ip_origen=ip,
        )
        return obj

    async def list_software(self):
        return await self.repo.get_software_all()

    @transactional
    async def update_software(self, id: int, schema: SoftwareUpdate, usuario_id=None, ip=None):
        sw = await self.repo.get_software_by_id(id)
        if not sw:
            raise HTTPException(404, detail="SOFTWARE_NOT_FOUND")
        obj = await self.repo.update_software(id, schema)
        await self.gov_repo.create_audit_log(
            "UPDATE", "INV_SOFTWARE",
            {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip_origen=ip,
        )
        return obj

    @transactional
    async def delete_software(self, id: int, usuario_id=None, ip=None):
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

    # =====================================================================
    # LICENCIAS
    # =====================================================================
    async def _license_key_counts(self, obj) -> dict[str, int]:
        estados = await self.repo.count_claves_by_estado(obj.LIC_Licencia)
        total = sum(estados.values())
        if total == 0 and obj.LIC_Clave_Activacion:
            assigned = 1 if obj.LIC_Cantidad_Usada else 0
            return {
                "total": 1,
                "disponibles": 0 if assigned else 1,
                "asignadas": assigned,
            }
        return {
            "total": total,
            "disponibles": estados.get("DISPONIBLE", 0),
            "asignadas": estados.get("ASIGNADA", 0),
        }

    async def _decorate_licencia_counts(self, obj):
        counts = await self._license_key_counts(obj)
        obj.LIC_Claves_Total = counts["total"]
        obj.LIC_Claves_Disponibles = counts["disponibles"]
        obj.LIC_Claves_Asignadas = counts["asignadas"]
        return obj

    async def _licencia_public_response(self, obj) -> dict:
        counts = await self._license_key_counts(obj)
        return {
            "LIC_Licencia": obj.LIC_Licencia,
            # License keys are only exposed by list_claves_licencia(), which is
            # admin-only and creates a VIEW_KEYS audit event.
            "LIC_Clave_Activacion": None,
            "LIC_Fecha_Vencimiento": obj.LIC_Fecha_Vencimiento,
            "LIC_Cantidad_Total": obj.LIC_Cantidad_Total,
            "LIC_Cantidad_Usada": obj.LIC_Cantidad_Usada,
            "SOF_Software": obj.SOF_Software,
            "TLI_Tipo_Licencia": obj.TLI_Tipo_Licencia,
            "LIC_Claves_Total": counts["total"],
            "LIC_Claves_Disponibles": counts["disponibles"],
            "LIC_Claves_Asignadas": counts["asignadas"],
        }

    async def create_licencia_in_transaction(
        self,
        schema: LicenciaCreate,
        usuario_id=None,
        ip=None,
        origen: str | None = None,
    ):
        sw = await self.db.execute(
            select(SoftwareModel).where(SoftwareModel.SOF_Software == schema.SOF_Software)
        )
        if not sw.scalar_one_or_none():
            raise HTTPException(404, detail="SOFTWARE_NOT_FOUND")
        if not await self.repo.get_tipo_licencia_by_id(schema.TLI_Tipo_Licencia):
            raise HTTPException(404, detail="LICENSE_TYPE_NOT_FOUND")
        if schema.LIC_Fecha_Vencimiento and schema.LIC_Fecha_Vencimiento < date.today():
            raise HTTPException(400, detail="LICENSE_EXPIRATION_IN_THE_PAST")

        claves = list(schema.LIC_Claves or [])
        if not claves and schema.LIC_Clave_Activacion and schema.LIC_Cantidad_Total == 1:
            claves = [LicenciaClaveCreate(LCL_Clave_Activacion=schema.LIC_Clave_Activacion)]

        fingerprints = [fingerprint_field(k.LCL_Clave_Activacion) for k in claves]
        if len(fingerprints) != len(set(fingerprints)):
            raise HTTPException(400, detail="DUPLICATE_LICENSE_KEY_IN_REQUEST")
        if await self.repo.count_claves_by_hashes(fingerprints) > 0:
            raise HTTPException(409, detail="LICENSE_KEY_ALREADY_EXISTS")

        payload = schema.model_copy(update={
            "LIC_Clave_Activacion": encrypt_field(schema.LIC_Clave_Activacion),
            "LIC_Claves": [],
        })
        obj = await self.repo.create_licencia(payload)

        for item, key_hash in zip(claves, fingerprints):
            await self.repo.create_licencia_clave(
                obj.LIC_Licencia,
                clave_cifrada=encrypt_field(item.LCL_Clave_Activacion),
                clave_hash=key_hash,
                referencia=item.LCL_Referencia,
            )

        await self.gov_repo.create_audit_log(
            "CREATE", "INV_LICENCIA",
            {
                "software_id": schema.SOF_Software,
                "cantidad_total": schema.LIC_Cantidad_Total,
                "claves_individuales": len(claves),
                "origen": origen,
            },
            usuario_id=usuario_id, ip_origen=ip,
        )
        await self.db.flush()
        return await self._decorate_licencia_counts(obj)

    @transactional
    async def create_licencia(self, schema: LicenciaCreate, usuario_id=None, ip=None):
        obj = await self.create_licencia_in_transaction(
            schema,
            usuario_id=usuario_id,
            ip=ip,
        )
        return await self._licencia_public_response(obj)

    async def list_licencias(self, software_id: int):
        items = await self.repo.get_licencias_by_software(software_id)
        return [await self._licencia_public_response(it) for it in items]

    async def get_licencia(self, id: int):
        obj = await self.repo.get_licencia_by_id(id)
        if not obj:
            raise HTTPException(404, "LICENSE_NOT_FOUND")
        return await self._licencia_public_response(obj)

    @transactional
    async def list_claves_licencia(self, licencia_id: int, usuario_id=None, ip=None):
        licencia = await self.repo.get_licencia_by_id(licencia_id)
        if not licencia:
            raise HTTPException(404, "LICENSE_NOT_FOUND")
        claves = await self.repo.get_claves_by_licencia(licencia_id)
        response: list[LicenciaClaveResponse] = []
        for clave in claves:
            instalacion_activa = next(
                (inst for inst in clave.instalaciones if inst.INS_Estado),
                None,
            )
            destino_tipo = None
            destino_id = None
            destino_nombre = None
            destino_detalle = None
            asignada_en = None

            if instalacion_activa:
                asignada_en = instalacion_activa.INS_Fecha_Instalacion
                if instalacion_activa.activo:
                    activo = instalacion_activa.activo
                    destino_tipo = "ACTIVO"
                    destino_id = str(instalacion_activa.ACT_Activo)
                    destino_nombre = activo.ACT_Codigo_Interno
                    destino_detalle = " / ".join(
                        part for part in (activo.ACT_Hostname, activo.ACT_Serie_Fabricante) if part
                    ) or None
                elif instalacion_activa.persona:
                    persona = instalacion_activa.persona
                    destino_tipo = "PERSONA"
                    destino_id = str(instalacion_activa.PER_Persona)
                    destino_nombre = " ".join(
                        part for part in (
                            persona.PER_Primer_Nombre,
                            persona.PER_Segundo_Nombre,
                            persona.PER_Primer_Apellido,
                            persona.PER_Segundo_Apellido,
                        ) if part
                    )
                    destino_detalle = persona.PER_Email_Corporativo

            response.append(
                LicenciaClaveResponse(
                    LCL_Licencia_Clave=clave.LCL_Licencia_Clave,
                    LIC_Licencia=clave.LIC_Licencia,
                    LCL_Clave_Activacion=decrypt_field(clave.LCL_Clave_Activacion) or "",
                    LCL_Referencia=clave.LCL_Referencia,
                    LCL_Estado=clave.LCL_Estado,
                    LCL_Creado_En=clave.created_at,
                    LCL_Asignada_En=asignada_en,
                    LCL_Destino_Tipo=destino_tipo,
                    LCL_Destino_Id=destino_id,
                    LCL_Destino_Nombre=destino_nombre,
                    LCL_Destino_Detalle=destino_detalle,
                )
            )

        if not response and licencia.LIC_Clave_Activacion:
            legacy_key = decrypt_field(licencia.LIC_Clave_Activacion) or ""
            if legacy_key:
                response.append(
                    LicenciaClaveResponse(
                        LCL_Licencia_Clave=-licencia.LIC_Licencia,
                        LIC_Licencia=licencia.LIC_Licencia,
                        LCL_Clave_Activacion=legacy_key,
                        LCL_Referencia="Clave legada",
                        LCL_Estado="ASIGNADA" if licencia.LIC_Cantidad_Usada else "DISPONIBLE",
                        LCL_Creado_En=None,
                        LCL_Asignada_En=None,
                        LCL_Destino_Tipo=None,
                        LCL_Destino_Id=None,
                        LCL_Destino_Nombre=None,
                        LCL_Destino_Detalle=None,
                    )
                )

        await self.gov_repo.create_audit_log(
            "VIEW_KEYS",
            "INV_LICENCIA_CLAVE",
            {
                "licencia_id": licencia_id,
                "claves_consultadas": len(response),
            },
            usuario_id=usuario_id,
            ip_origen=ip,
        )
        return response

    @transactional
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
        return await self._licencia_public_response(updated)

    @transactional
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
        except IntegrityError:
            raise HTTPException(409, "CANNOT_DELETE_LICENSE_IN_USE")

    async def list_instalaciones_by_activo(self, activo_id: uuid.UUID, solo_activas: bool = True):
        """Lista las instalaciones (con software/tipo_licencia poblados) de un activo."""
        return await self.repo.get_instalaciones_by_activo(activo_id, solo_activas=solo_activas)

    async def list_instalaciones_by_persona(self, persona_id: uuid.UUID, solo_activas: bool = True):
        persona = (await self.db.execute(
            select(Persona).where(Persona.PER_Persona == persona_id)
        )).scalar_one_or_none()
        if not persona:
            raise HTTPException(404, "PERSON_NOT_FOUND")
        return await self.repo.get_instalaciones_by_persona(persona_id, solo_activas=solo_activas)

    # =====================================================================
    # INSTALACIONES — Operación ACID con UPDATE atómico
    # =====================================================================
    @transactional
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
        if schema.ACT_Activo is not None:
            activo = (await self.db.execute(
                select(Activo).where(Activo.ACT_Activo == schema.ACT_Activo)
            )).scalar_one_or_none()
            if not activo:
                raise HTTPException(404, detail="ASSET_NOT_FOUND")
        if schema.PER_Persona is not None:
            persona = (await self.db.execute(
                select(Persona).where(Persona.PER_Persona == schema.PER_Persona)
            )).scalar_one_or_none()
            if not persona:
                raise HTTPException(404, detail="PERSON_NOT_FOUND")
            if not persona.PER_Estado:
                raise HTTPException(400, detail="PERSON_INACTIVE")

        existe = await self.repo.get_instalacion_activa(
            schema.LIC_Licencia,
            activo_id=schema.ACT_Activo,
            persona_id=schema.PER_Persona,
        )
        if existe:
            raise HTTPException(400, detail="LICENSE_ALREADY_ASSIGNED_TO_TARGET")

        clave_reservada_id = schema.LCL_Licencia_Clave
        total_claves = await self.repo.count_claves_by_licencia(schema.LIC_Licencia)
        if clave_reservada_id is not None:
            clave = await self.repo.get_clave_by_id(clave_reservada_id)
            if not clave or clave.LIC_Licencia != schema.LIC_Licencia:
                raise HTTPException(404, detail="LICENSE_KEY_NOT_FOUND")
            if not await self.repo.reservar_clave_licencia(schema.LIC_Licencia, clave_reservada_id):
                raise HTTPException(409, detail="LICENSE_KEY_NOT_AVAILABLE")
        elif total_claves > 0:
            clave = await self.repo.reservar_clave_disponible(schema.LIC_Licencia)
            if not clave:
                raise HTTPException(409, detail="NO_LICENSE_KEYS_AVAILABLE")
            clave_reservada_id = clave.LCL_Licencia_Clave

        reservado = await self.repo.reservar_cupo_licencia(schema.LIC_Licencia)
        if not reservado:
            licencia = await self.repo.get_licencia_by_id(schema.LIC_Licencia)
            if not licencia:
                raise HTTPException(404, detail="LICENSE_NOT_FOUND")
            raise HTTPException(409, detail="NO_LICENSE_SEATS_AVAILABLE")

        schema_to_create = schema.model_copy(update={"LCL_Licencia_Clave": clave_reservada_id})
        instalacion = await self.repo.create_instalacion(schema_to_create)
        await self.gov_repo.create_audit_log(
            "INSTALL", "INV_INSTALACION",
            {
                "activo": str(schema.ACT_Activo) if schema.ACT_Activo else None,
                "persona": str(schema.PER_Persona) if schema.PER_Persona else None,
                "licencia": schema.LIC_Licencia,
                "licencia_clave": clave_reservada_id,
            },
            usuario_id=usuario_id, ip_origen=ip,
        )
        return instalacion

    @transactional
    async def desinstalar_software(
        self,
        schema: InstalacionCreate,
        usuario_id: uuid.UUID | None = None,
        ip: str | None = None,
    ):
        """
        UPDATE condicional para que doble-desinstalación no decremente dos veces.
        """
        instalacion_actual = await self.repo.get_instalacion_activa(
            schema.LIC_Licencia,
            activo_id=schema.ACT_Activo,
            persona_id=schema.PER_Persona,
        )
        if not instalacion_actual:
            raise HTTPException(404, detail="INSTALLATION_NOT_FOUND_OR_ALREADY_REMOVED")

        desactivado = await self.repo.desactivar_instalacion_atomico(
            schema.LIC_Licencia,
            activo_id=schema.ACT_Activo,
            persona_id=schema.PER_Persona,
        )
        if not desactivado:
            raise HTTPException(404, detail="INSTALLATION_NOT_FOUND_OR_ALREADY_REMOVED")

        await self.repo.liberar_cupo_licencia(schema.LIC_Licencia)
        if instalacion_actual.LCL_Licencia_Clave is not None:
            await self.repo.liberar_clave_licencia(instalacion_actual.LCL_Licencia_Clave)

        await self.gov_repo.create_audit_log(
            "UNINSTALL", "INV_INSTALACION",
            {
                "activo": str(schema.ACT_Activo) if schema.ACT_Activo else None,
                "persona": str(schema.PER_Persona) if schema.PER_Persona else None,
                "licencia": schema.LIC_Licencia,
                "licencia_clave": instalacion_actual.LCL_Licencia_Clave,
            },
            usuario_id=usuario_id, ip_origen=ip,
        )
        return {"status": "success", "message": "SOFTWARE_UNINSTALLED_SUCCESSFULLY"}
