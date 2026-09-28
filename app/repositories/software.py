"""
Repositorio de Software/Licencias/Instalaciones.

Reglas de transacción:
- Los repos NO commitean. Solo hacen `flush()` cuando necesitan que se asigne PK.
- El servicio es responsable del commit/rollback al final del flujo.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from sqlalchemy import delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.models.software import Instalacion, Licencia, LicenciaClave, Software, TipoLicencia
from app.repositories.base import BaseRepository
from app.schemas.software import (
    InstalacionCreate,
    LicenciaCreate,
    LicenciaUpdate,
    SoftwareCreate,
    SoftwareUpdate,
    TipoLicenciaCreate,
    TipoLicenciaUpdate,
)


class SoftwareRepository(BaseRepository):
    # =====================================================================
    # TIPO LICENCIA
    # =====================================================================
    async def create_tipo_licencia(self, schema: TipoLicenciaCreate) -> TipoLicencia:
        obj = TipoLicencia(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_tipos_licencia(self) -> List[TipoLicencia]:
        result = await self.db.execute(select(TipoLicencia))
        return result.scalars().all()

    async def get_tipo_licencia_by_id(self, id: int) -> Optional[TipoLicencia]:
        result = await self.db.execute(
            select(TipoLicencia).where(TipoLicencia.TLI_Tipo_Licencia == id)
        )
        return result.scalar_one_or_none()

    async def update_tipo_licencia(self, id: int, schema: TipoLicenciaUpdate) -> Optional[TipoLicencia]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(TipoLicencia)
                .where(TipoLicencia.TLI_Tipo_Licencia == id)
                .values(**data)
            )
            await self.db.flush()
        return await self.get_tipo_licencia_by_id(id)

    async def count_licencias_by_tipo(self, tipo_id: int) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(Licencia).where(Licencia.TLI_Tipo_Licencia == tipo_id)
        )
        return result.scalar_one()

    async def delete_tipo_licencia(self, id: int):
        await self.db.execute(
            delete(TipoLicencia).where(TipoLicencia.TLI_Tipo_Licencia == id)
        )

    # =====================================================================
    # SOFTWARE
    # =====================================================================
    async def create_software(self, schema: SoftwareCreate) -> Software:
        obj = Software(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_software_all(self) -> List[Software]:
        result = await self.db.execute(select(Software))
        return result.scalars().all()

    async def get_software_by_id(self, id: int) -> Optional[Software]:
        result = await self.db.execute(select(Software).where(Software.SOF_Software == id))
        return result.scalar_one_or_none()

    async def update_software(self, id: int, schema: SoftwareUpdate) -> Optional[Software]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(Software).where(Software.SOF_Software == id).values(**data)
            )
            await self.db.flush()
        return await self.get_software_by_id(id)

    async def count_licencias_by_software(self, software_id: int) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(Licencia).where(Licencia.SOF_Software == software_id)
        )
        return result.scalar_one()

    async def delete_software(self, id: int):
        await self.db.execute(delete(Software).where(Software.SOF_Software == id))

    # =====================================================================
    # LICENCIAS
    # =====================================================================
    async def create_licencia(self, schema: LicenciaCreate) -> Licencia:
        obj = Licencia(**schema.model_dump(exclude={"LIC_Claves"}))
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def create_licencia_clave(
        self,
        licencia_id: int,
        *,
        clave_cifrada: str,
        clave_hash: str,
        referencia: str | None = None,
    ) -> LicenciaClave:
        obj = LicenciaClave(
            LIC_Licencia=licencia_id,
            LCL_Clave_Activacion=clave_cifrada,
            LCL_Clave_Hash=clave_hash,
            LCL_Referencia=referencia,
            LCL_Estado="DISPONIBLE",
        )
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_claves_by_licencia(self, licencia_id: int) -> List[LicenciaClave]:
        result = await self.db.execute(
            select(LicenciaClave)
            .options(
                selectinload(LicenciaClave.instalaciones).selectinload(Instalacion.activo),
                selectinload(LicenciaClave.instalaciones).selectinload(Instalacion.persona),
            )
            .where(LicenciaClave.LIC_Licencia == licencia_id)
            .order_by(LicenciaClave.LCL_Licencia_Clave)
        )
        return result.scalars().all()

    async def get_clave_by_id(self, clave_id: int) -> Optional[LicenciaClave]:
        result = await self.db.execute(
            select(LicenciaClave).where(LicenciaClave.LCL_Licencia_Clave == clave_id)
        )
        return result.scalar_one_or_none()

    async def count_claves_by_hashes(self, hashes: list[str]) -> int:
        if not hashes:
            return 0
        result = await self.db.execute(
            select(func.count())
            .select_from(LicenciaClave)
            .where(LicenciaClave.LCL_Clave_Hash.in_(hashes))
        )
        return result.scalar_one()

    async def count_claves_by_licencia(self, licencia_id: int) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(LicenciaClave).where(LicenciaClave.LIC_Licencia == licencia_id)
        )
        return result.scalar_one()

    async def count_claves_by_estado(self, licencia_id: int) -> dict[str, int]:
        result = await self.db.execute(
            select(LicenciaClave.LCL_Estado, func.count())
            .where(LicenciaClave.LIC_Licencia == licencia_id)
            .group_by(LicenciaClave.LCL_Estado)
        )
        return {estado: count for estado, count in result.all()}

    async def reservar_clave_licencia(
        self,
        licencia_id: int,
        clave_id: int,
    ) -> bool:
        result = await self.db.execute(
            update(LicenciaClave)
            .where(
                LicenciaClave.LCL_Licencia_Clave == clave_id,
                LicenciaClave.LIC_Licencia == licencia_id,
                LicenciaClave.LCL_Estado == "DISPONIBLE",
            )
            .values(LCL_Estado="ASIGNADA")
        )
        await self.db.flush()
        return result.rowcount == 1

    async def reservar_clave_disponible(self, licencia_id: int) -> Optional[LicenciaClave]:
        result = await self.db.execute(
            select(LicenciaClave.LCL_Licencia_Clave)
            .where(
                LicenciaClave.LIC_Licencia == licencia_id,
                LicenciaClave.LCL_Estado == "DISPONIBLE",
            )
            .order_by(LicenciaClave.LCL_Licencia_Clave)
            .limit(20)
        )
        for clave_id in result.scalars().all():
            if await self.reservar_clave_licencia(licencia_id, clave_id):
                return await self.get_clave_by_id(clave_id)
        return None

    async def liberar_clave_licencia(self, clave_id: int) -> bool:
        result = await self.db.execute(
            update(LicenciaClave)
            .where(
                LicenciaClave.LCL_Licencia_Clave == clave_id,
                LicenciaClave.LCL_Estado == "ASIGNADA",
            )
            .values(LCL_Estado="DISPONIBLE")
        )
        await self.db.flush()
        return result.rowcount == 1

    async def get_licencia_by_id(self, id: int) -> Optional[Licencia]:
        result = await self.db.execute(select(Licencia).where(Licencia.LIC_Licencia == id))
        return result.scalar_one_or_none()

    async def get_licencias_by_software(self, software_id: int) -> List[Licencia]:
        result = await self.db.execute(
            select(Licencia).where(Licencia.SOF_Software == software_id)
        )
        return result.scalars().all()

    async def update_licencia(self, id: int, schema: LicenciaUpdate) -> Optional[Licencia]:
        data = schema.model_dump(exclude_unset=True)
        if data:
            await self.db.execute(
                update(Licencia).where(Licencia.LIC_Licencia == id).values(**data)
            )
            await self.db.flush()
        return await self.get_licencia_by_id(id)

    async def delete_licencia(self, id: int):
        await self.db.execute(delete(Licencia).where(Licencia.LIC_Licencia == id))
        await self.db.flush()

    async def count_instalaciones_activas_de_licencia(self, id: int) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(Instalacion)
            .where(Instalacion.LIC_Licencia == id, Instalacion.INS_Estado.is_(True))
        )
        return result.scalar_one()

    async def reservar_cupo_licencia(self, licencia_id: int) -> bool:
        """
        UPDATE condicional ATÓMICO: incrementa LIC_Cantidad_Usada solo si
        aún hay cupos disponibles. Retorna True si reservó, False si no.

        Esto elimina la race condition clásica del patrón "read-then-write".
        """
        result = await self.db.execute(
            update(Licencia)
            .where(
                Licencia.LIC_Licencia == licencia_id,
                Licencia.LIC_Cantidad_Usada < Licencia.LIC_Cantidad_Total,
            )
            .values(LIC_Cantidad_Usada=Licencia.LIC_Cantidad_Usada + 1)
        )
        return result.rowcount == 1

    async def liberar_cupo_licencia(self, licencia_id: int) -> bool:
        """UPDATE condicional: decrementa solo si > 0 (nunca por debajo de cero)."""
        result = await self.db.execute(
            update(Licencia)
            .where(
                Licencia.LIC_Licencia == licencia_id,
                Licencia.LIC_Cantidad_Usada > 0,
            )
            .values(LIC_Cantidad_Usada=Licencia.LIC_Cantidad_Usada - 1)
        )
        return result.rowcount == 1

    # =====================================================================
    # INSTALACIONES
    # =====================================================================
    async def create_instalacion(self, schema: InstalacionCreate) -> Instalacion:
        obj = Instalacion(**schema.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_instalaciones_by_activo(
        self, activo_id: uuid.UUID, solo_activas: bool = True
    ) -> List[Instalacion]:
        """Lista todas las instalaciones de un activo (opcional: solo las activas)."""
        from sqlalchemy.orm import selectinload
        query = (
            select(Instalacion)
            .options(
                selectinload(Instalacion.licencia).selectinload(Licencia.software),
                selectinload(Instalacion.licencia).selectinload(Licencia.tipo_licencia),
            )
            .where(Instalacion.ACT_Activo == activo_id)
        )
        if solo_activas:
            query = query.where(Instalacion.INS_Estado.is_(True))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_instalaciones_by_persona(
        self, persona_id: uuid.UUID, solo_activas: bool = True
    ) -> List[Instalacion]:
        from sqlalchemy.orm import selectinload
        query = (
            select(Instalacion)
            .options(
                selectinload(Instalacion.licencia).selectinload(Licencia.software),
                selectinload(Instalacion.licencia).selectinload(Licencia.tipo_licencia),
            )
            .where(Instalacion.PER_Persona == persona_id)
        )
        if solo_activas:
            query = query.where(Instalacion.INS_Estado.is_(True))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_instalacion_activa(
        self,
        licencia_id: int,
        *,
        activo_id: uuid.UUID | None = None,
        persona_id: uuid.UUID | None = None,
    ) -> Optional[Instalacion]:
        if (activo_id is None) == (persona_id is None):
            raise ValueError("INSTALLATION_TARGET_XOR_REQUIRED")
        query = select(Instalacion).where(
            Instalacion.LIC_Licencia == licencia_id,
            Instalacion.INS_Estado.is_(True),
        )
        if activo_id is not None:
            query = query.where(Instalacion.ACT_Activo == activo_id)
        else:
            query = query.where(Instalacion.PER_Persona == persona_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def desactivar_instalacion_atomico(
        self,
        licencia_id: int,
        *,
        activo_id: uuid.UUID | None = None,
        persona_id: uuid.UUID | None = None,
    ) -> bool:
        """
        UPDATE condicional: solo desactiva si está activa. Retorna True si
        cambió 1 fila. Esto previene doble-desinstalación que decrementa
        el contador dos veces.
        """
        if (activo_id is None) == (persona_id is None):
            raise ValueError("INSTALLATION_TARGET_XOR_REQUIRED")
        target_filter = (
            Instalacion.ACT_Activo == activo_id
            if activo_id is not None
            else Instalacion.PER_Persona == persona_id
        )
        result = await self.db.execute(
            update(Instalacion)
            .where(
                target_filter,
                Instalacion.LIC_Licencia == licencia_id,
                Instalacion.INS_Estado.is_(True),
            )
            .values(INS_Estado=False)
        )
        return result.rowcount == 1

    async def liberar_instalaciones_por_destino(
        self,
        *,
        activos_ids: list[uuid.UUID] | None = None,
        persona_id: uuid.UUID | None = None,
    ) -> int:
        conditions = []
        if activos_ids:
            conditions.append(Instalacion.ACT_Activo.in_(activos_ids))
        if persona_id:
            conditions.append(Instalacion.PER_Persona == persona_id)
        if not conditions:
            return 0

        from sqlalchemy import or_

        result = await self.db.execute(
            select(Instalacion).where(
                or_(*conditions),
                Instalacion.INS_Estado.is_(True),
            )
        )
        instalaciones = result.scalars().all()
        if not instalaciones:
            return 0

        ids = [inst.INS_Instalacion for inst in instalaciones]
        claves_ids = [
            inst.LCL_Licencia_Clave for inst in instalaciones
            if inst.LCL_Licencia_Clave is not None
        ]
        conteo_por_licencia: dict[int, int] = {}
        for inst in instalaciones:
            conteo_por_licencia[inst.LIC_Licencia] = conteo_por_licencia.get(inst.LIC_Licencia, 0) + 1

        await self.db.execute(
            update(Instalacion)
            .where(Instalacion.INS_Instalacion.in_(ids), Instalacion.INS_Estado.is_(True))
            .values(INS_Estado=False)
        )
        for licencia_id, cantidad in conteo_por_licencia.items():
            await self.db.execute(
                update(Licencia)
                .where(
                    Licencia.LIC_Licencia == licencia_id,
                    Licencia.LIC_Cantidad_Usada >= cantidad,
                )
                .values(LIC_Cantidad_Usada=Licencia.LIC_Cantidad_Usada - cantidad)
            )
        if claves_ids:
            await self.db.execute(
                update(LicenciaClave)
                .where(
                    LicenciaClave.LCL_Licencia_Clave.in_(claves_ids),
                    LicenciaClave.LCL_Estado == "ASIGNADA",
                )
                .values(LCL_Estado="DISPONIBLE")
            )
        await self.db.flush()
        return len(instalaciones)
