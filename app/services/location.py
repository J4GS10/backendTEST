"""Servicio de Ubicación geográfica (PaisEstadoMunicipioSedeEdificioNivelArea)."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_scope import current_scope, require_owned, require_sede, visible_sede_ids
from app.core.transactional import commit_or_409
from app.repositories.governance import GovernanceRepository
from app.repositories.location import LocationRepository
from app.services.base import BaseService
from app.schemas.location import (
    AreaCreate, AreaUpdate,
    EdificioCreate, EdificioUpdate,
    EstadoCreate, EstadoUpdate,
    MunicipioCreate, MunicipioUpdate,
    NivelCreate, NivelUpdate,
    PaisCreate, PaisUpdate,
    SedeCreate, SedeUpdate,
)


class LocationService(BaseService[LocationRepository]):
    repo_class = LocationRepository

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.gov_repo = GovernanceRepository(db)

    # -------- helpers ----------
    async def _exists(self, getter, id: int, err: str):
        obj = await getter(id)
        if not obj:
            raise HTTPException(404, err)
        return obj

    async def _no_children(self, count_fn, parent_id: int, err: str):
        if await count_fn(parent_id) > 0:
            raise HTTPException(409, err)

    async def _commit_audit(self, *, accion: str, entidad: str, snapshot: dict, usuario_id, ip, sede=None):
        await self.gov_repo.create_audit_log(
            accion, entidad, snapshot, usuario_id=usuario_id, ip_origen=ip, sede_id=sede,
        )
        await commit_or_409(self.db, where=f"LocationService.{entidad}")

    # -------- alcance por sede ----------
    @staticmethod
    def _require_global() -> None:
        """País, estado, municipio y sede son jerarquía compartida: solo alcance global."""
        scope = current_scope()
        if scope is not None and scope.restricted:
            raise HTTPException(403, "GLOBAL_SCOPE_REQUIRED")

    async def _sede_de_edificio(self, edificio_id: int) -> int | None:
        edificio = await self._exists(self.repo.get_edificio_by_id, edificio_id, "BUILDING_NOT_FOUND")
        return edificio.SED_Sede

    async def _sede_de_nivel(self, nivel_id: int) -> int | None:
        nivel = await self._exists(self.repo.get_nivel_by_id, nivel_id, "LEVEL_NOT_FOUND")
        return await self._sede_de_edificio(nivel.EDI_Edificio)

    async def _sede_de_area(self, area_id: int) -> int | None:
        area = await self._exists(self.repo.get_area_by_id, area_id, "AREA_NOT_FOUND")
        return await self._sede_de_nivel(area.NIV_Nivel)

    @staticmethod
    def _en_alcance(sede_id: int | None) -> bool:
        scope = current_scope()
        return scope is None or scope.allows(sede_id)

    # =====================================================================
    # PAIS
    # =====================================================================
    async def create_pais(self, schema: PaisCreate, usuario_id=None, ip=None):
        self._require_global()
        obj = await self.repo.create_pais(schema)
        await self._commit_audit(
            accion="CREATE", entidad="INV_PAIS",
            snapshot={"nombre": schema.PAI_Nombre, "iso": schema.PAI_Codigo_ISO},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def list_paises(self):
        return await self.repo.get_paises()

    async def get_pais(self, id: int):
        return await self._exists(self.repo.get_pais_by_id, id, "COUNTRY_NOT_FOUND")

    async def update_pais(self, id: int, schema: PaisUpdate, usuario_id=None, ip=None):
        self._require_global()
        await self._exists(self.repo.get_pais_by_id, id, "COUNTRY_NOT_FOUND")
        obj = await self.repo.update_pais(id, schema)
        await self._commit_audit(
            accion="UPDATE", entidad="INV_PAIS",
            snapshot={"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def delete_pais(self, id: int, usuario_id=None, ip=None):
        self._require_global()
        obj = await self._exists(self.repo.get_pais_by_id, id, "COUNTRY_NOT_FOUND")
        await self._no_children(self.repo.count_estados_by_pais, id, "CANNOT_DELETE_COUNTRY_HAS_STATES")
        await self.repo.delete_pais(id)
        await self._commit_audit(
            accion="DELETE", entidad="INV_PAIS",
            snapshot={"id": id, "nombre": obj.PAI_Nombre},
            usuario_id=usuario_id, ip=ip,
        )

    # =====================================================================
    # ESTADO
    # =====================================================================
    async def create_estado(self, schema: EstadoCreate, usuario_id=None, ip=None):
        self._require_global()
        obj = await self.repo.create_estado(schema)
        await self._commit_audit(
            accion="CREATE", entidad="INV_ESTADO",
            snapshot={"nombre": schema.EST_Nombre, "pais_id": schema.PAI_Pais},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def list_estados(self, pais_id: int):
        return await self.repo.get_estados_by_pais(pais_id)

    async def get_estado(self, id: int):
        return await self._exists(self.repo.get_estado_by_id, id, "STATE_NOT_FOUND")

    async def update_estado(self, id: int, schema: EstadoUpdate, usuario_id=None, ip=None):
        self._require_global()
        await self._exists(self.repo.get_estado_by_id, id, "STATE_NOT_FOUND")
        obj = await self.repo.update_estado(id, schema)
        await self._commit_audit(
            accion="UPDATE", entidad="INV_ESTADO",
            snapshot={"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def delete_estado(self, id: int, usuario_id=None, ip=None):
        self._require_global()
        obj = await self._exists(self.repo.get_estado_by_id, id, "STATE_NOT_FOUND")
        await self._no_children(self.repo.count_municipios_by_estado, id, "CANNOT_DELETE_STATE_HAS_MUNICIPALITIES")
        await self.repo.delete_estado(id)
        await self._commit_audit(
            accion="DELETE", entidad="INV_ESTADO",
            snapshot={"id": id, "nombre": obj.EST_Nombre},
            usuario_id=usuario_id, ip=ip,
        )

    # =====================================================================
    # MUNICIPIO
    # =====================================================================
    async def create_municipio(self, schema: MunicipioCreate, usuario_id=None, ip=None):
        self._require_global()
        obj = await self.repo.create_municipio(schema)
        await self._commit_audit(
            accion="CREATE", entidad="INV_MUNICIPIO",
            snapshot={"nombre": schema.MUN_Nombre, "estado_id": schema.EST_Estado},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def list_municipios(self, estado_id: int):
        return await self.repo.get_municipios_by_estado(estado_id)

    async def get_municipio(self, id: int):
        return await self._exists(self.repo.get_municipio_by_id, id, "MUNICIPALITY_NOT_FOUND")

    async def update_municipio(self, id: int, schema: MunicipioUpdate, usuario_id=None, ip=None):
        self._require_global()
        await self._exists(self.repo.get_municipio_by_id, id, "MUNICIPALITY_NOT_FOUND")
        obj = await self.repo.update_municipio(id, schema)
        await self._commit_audit(
            accion="UPDATE", entidad="INV_MUNICIPIO",
            snapshot={"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def delete_municipio(self, id: int, usuario_id=None, ip=None):
        self._require_global()
        obj = await self._exists(self.repo.get_municipio_by_id, id, "MUNICIPALITY_NOT_FOUND")
        await self._no_children(self.repo.count_sedes_by_municipio, id, "CANNOT_DELETE_MUNICIPALITY_HAS_SITES")
        await self.repo.delete_municipio(id)
        await self._commit_audit(
            accion="DELETE", entidad="INV_MUNICIPIO",
            snapshot={"id": id, "nombre": obj.MUN_Nombre},
            usuario_id=usuario_id, ip=ip,
        )

    # =====================================================================
    # SEDE
    # =====================================================================
    async def create_sede(self, schema: SedeCreate, usuario_id=None, ip=None):
        self._require_global()
        obj = await self.repo.create_sede(schema)
        await self._commit_audit(
            accion="CREATE", entidad="INV_SEDE",
            snapshot={"nombre": schema.SED_Nombre},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def list_sedes(self, municipio_id: int):
        return [s for s in await self.repo.get_sedes_by_municipio(municipio_id) if self._en_alcance(s.SED_Sede)]

    async def list_sedes_en_alcance(self) -> list[dict]:
        """Sedes que el usuario puede ver (todas si es global), con su ubicación."""
        from sqlalchemy import select as _select
        from sqlalchemy.orm import selectinload
        from app.models.location import Estado, Municipio, Sede
        stmt = _select(Sede).options(
            selectinload(Sede.municipio).selectinload(Municipio.estado).selectinload(Estado.pais)
        ).order_by(Sede.SED_Nombre)
        ids = visible_sede_ids()
        if ids is not None:
            stmt = stmt.where(Sede.SED_Sede.in_(ids))
        sedes = (await self.db.execute(stmt)).scalars().all()
        out = []
        for sede in sedes:
            mun = getattr(sede, "municipio", None)
            est = getattr(mun, "estado", None) if mun else None
            pais = getattr(est, "pais", None) if est else None
            out.append({
                "SED_Sede": sede.SED_Sede,
                "SED_Nombre": sede.SED_Nombre,
                "ubicacion": ", ".join(p for p in (
                    mun.MUN_Nombre if mun else None,
                    pais.PAI_Nombre if pais else None,
                ) if p),
            })
        return out

    async def get_sede(self, id: int):
        sede = await self._exists(self.repo.get_sede_by_id, id, "SITE_NOT_FOUND")
        if not self._en_alcance(sede.SED_Sede):
            raise HTTPException(404, "SITE_NOT_FOUND")
        return sede

    async def update_sede(self, id: int, schema: SedeUpdate, usuario_id=None, ip=None):
        self._require_global()
        await self._exists(self.repo.get_sede_by_id, id, "SITE_NOT_FOUND")
        obj = await self.repo.update_sede(id, schema)
        await self._commit_audit(
            accion="UPDATE", entidad="INV_SEDE",
            snapshot={"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def delete_sede(self, id: int, usuario_id=None, ip=None):
        self._require_global()
        obj = await self._exists(self.repo.get_sede_by_id, id, "SITE_NOT_FOUND")
        await self._no_children(self.repo.count_edificios_by_sede, id, "CANNOT_DELETE_SITE_HAS_BUILDINGS")
        await self.repo.delete_sede(id)
        await self._commit_audit(
            accion="DELETE", entidad="INV_SEDE",
            snapshot={"id": id, "nombre": obj.SED_Nombre},
            usuario_id=usuario_id, ip=ip,
        )

    # =====================================================================
    # EDIFICIO
    # =====================================================================
    async def create_edificio(self, schema: EdificioCreate, usuario_id=None, ip=None):
        require_sede(schema.SED_Sede)
        obj = await self.repo.create_edificio(schema)
        await self._commit_audit(
            accion="CREATE", entidad="INV_EDIFICIO",
            snapshot={"nombre": schema.EDI_Nombre, "sede_id": schema.SED_Sede},
            usuario_id=usuario_id, ip=ip, sede=schema.SED_Sede,
        )
        return obj

    async def list_edificios(self, sede_id: int):
        if not self._en_alcance(sede_id):
            return []
        return await self.repo.get_edificios_by_sede(sede_id)

    async def get_edificio(self, id: int):
        edificio = await self._exists(self.repo.get_edificio_by_id, id, "BUILDING_NOT_FOUND")
        if not self._en_alcance(edificio.SED_Sede):
            raise HTTPException(404, "BUILDING_NOT_FOUND")
        return edificio

    async def update_edificio(self, id: int, schema: EdificioUpdate, usuario_id=None, ip=None):
        require_owned(await self._sede_de_edificio(id))
        if getattr(schema, "SED_Sede", None) is not None:
            require_sede(schema.SED_Sede)
        obj = await self.repo.update_edificio(id, schema)
        await self._commit_audit(
            accion="UPDATE", entidad="INV_EDIFICIO",
            snapshot={"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def delete_edificio(self, id: int, usuario_id=None, ip=None):
        obj = await self._exists(self.repo.get_edificio_by_id, id, "BUILDING_NOT_FOUND")
        require_owned(obj.SED_Sede)
        await self._no_children(self.repo.count_niveles_by_edificio, id, "CANNOT_DELETE_BUILDING_HAS_LEVELS")
        await self.repo.delete_edificio(id)
        await self._commit_audit(
            accion="DELETE", entidad="INV_EDIFICIO",
            snapshot={"id": id, "nombre": obj.EDI_Nombre},
            usuario_id=usuario_id, ip=ip,
        )

    # =====================================================================
    # NIVEL
    # =====================================================================
    async def create_nivel(self, schema: NivelCreate, usuario_id=None, ip=None):
        require_owned(await self._sede_de_edificio(schema.EDI_Edificio))
        obj = await self.repo.create_nivel(schema)
        await self._commit_audit(
            accion="CREATE", entidad="INV_NIVEL",
            snapshot={"piso": schema.NIV_Numero_Piso, "edificio_id": schema.EDI_Edificio},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def list_niveles(self, edificio_id: int):
        edificio = await self.repo.get_edificio_by_id(edificio_id)
        if edificio is None or not self._en_alcance(edificio.SED_Sede):
            return []
        return await self.repo.get_niveles_by_edificio(edificio_id)

    async def get_nivel(self, id: int):
        nivel = await self._exists(self.repo.get_nivel_by_id, id, "LEVEL_NOT_FOUND")
        if not self._en_alcance(await self._sede_de_edificio(nivel.EDI_Edificio)):
            raise HTTPException(404, "LEVEL_NOT_FOUND")
        return nivel

    async def update_nivel(self, id: int, schema: NivelUpdate, usuario_id=None, ip=None):
        require_owned(await self._sede_de_nivel(id))
        if getattr(schema, "EDI_Edificio", None) is not None:
            require_owned(await self._sede_de_edificio(schema.EDI_Edificio))
        obj = await self.repo.update_nivel(id, schema)
        await self._commit_audit(
            accion="UPDATE", entidad="INV_NIVEL",
            snapshot={"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def delete_nivel(self, id: int, usuario_id=None, ip=None):
        obj = await self._exists(self.repo.get_nivel_by_id, id, "LEVEL_NOT_FOUND")
        require_owned(await self._sede_de_edificio(obj.EDI_Edificio))
        await self._no_children(self.repo.count_areas_by_nivel, id, "CANNOT_DELETE_LEVEL_HAS_AREAS")
        await self.repo.delete_nivel(id)
        await self._commit_audit(
            accion="DELETE", entidad="INV_NIVEL",
            snapshot={"id": id, "piso": obj.NIV_Numero_Piso},
            usuario_id=usuario_id, ip=ip,
        )

    # =====================================================================
    # AREA
    # =====================================================================
    async def create_area(self, schema: AreaCreate, usuario_id=None, ip=None):
        require_owned(await self._sede_de_nivel(schema.NIV_Nivel))
        obj = await self.repo.create_area(schema)
        await self._commit_audit(
            accion="CREATE", entidad="INV_AREA",
            snapshot={"nombre": schema.ARE_Nombre, "nivel_id": schema.NIV_Nivel},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def list_areas(self, nivel_id: int):
        nivel = await self.repo.get_nivel_by_id(nivel_id)
        if nivel is None or not self._en_alcance(await self._sede_de_edificio(nivel.EDI_Edificio)):
            return []
        return await self.repo.get_areas_by_nivel(nivel_id)

    async def list_all_areas_hierarchy(self) -> list[dict]:
        rows = await self.repo.get_all_areas_with_hierarchy()
        output = []
        for area in rows:
            nivel = area.nivel
            edificio = nivel.edificio if nivel else None
            sede = edificio.sede if edificio else None
            # Selector de áreas: solo las de las sedes del alcance.
            if not self._en_alcance(sede.SED_Sede if sede else None):
                continue
            path_parts = [
                sede.SED_Nombre if sede else None,
                edificio.EDI_Nombre if edificio else None,
                f"Piso {nivel.NIV_Numero_Piso}" if nivel else None,
                area.ARE_Nombre,
            ]
            output.append({
                "ARE_Area": area.ARE_Area,
                "ARE_Nombre": area.ARE_Nombre,
                "ARE_Tipo_Acceso": area.ARE_Tipo_Acceso,
                "NIV_Nivel": area.NIV_Nivel,
                "SED_Sede": sede.SED_Sede if sede else None,
                "ruta": " › ".join(part for part in path_parts if part),
            })
        return output

    async def get_area(self, id: int):
        area = await self._exists(self.repo.get_area_by_id, id, "AREA_NOT_FOUND")
        if not self._en_alcance(await self._sede_de_nivel(area.NIV_Nivel)):
            raise HTTPException(404, "AREA_NOT_FOUND")
        return area

    async def update_area(self, id: int, schema: AreaUpdate, usuario_id=None, ip=None):
        require_owned(await self._sede_de_area(id))
        if getattr(schema, "NIV_Nivel", None) is not None:
            require_owned(await self._sede_de_nivel(schema.NIV_Nivel))
        obj = await self.repo.update_area(id, schema)
        await self._commit_audit(
            accion="UPDATE", entidad="INV_AREA",
            snapshot={"id": id, "cambios": schema.model_dump(exclude_unset=True)},
            usuario_id=usuario_id, ip=ip,
        )
        return obj

    async def delete_area(self, id: int, usuario_id=None, ip=None):
        obj = await self._exists(self.repo.get_area_by_id, id, "AREA_NOT_FOUND")
        require_owned(await self._sede_de_nivel(obj.NIV_Nivel))
        try:
            await self.repo.delete_area(id)
            await self._commit_audit(
                accion="DELETE", entidad="INV_AREA",
                snapshot={"id": id, "nombre": obj.ARE_Nombre},
                usuario_id=usuario_id, ip=ip,
            )
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(409, "CANNOT_DELETE_AREA_IN_USE")

    # Alias retro-compatibilidad
    get_area_detail = get_area
