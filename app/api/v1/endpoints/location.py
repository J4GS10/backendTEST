"""Ubicación geográfica. Lectura: cualquier autenticado. Mutación: ADMIN+."""
from typing import List
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_client_ip, require_admin
from app.db.session import get_db
from app.schemas.location import (
    AreaCreate, AreaResponse, AreaUpdate,
    EdificioCreate, EdificioResponse, EdificioUpdate,
    EstadoCreate, EstadoResponse, EstadoUpdate,
    MunicipioCreate, MunicipioResponse, MunicipioUpdate,
    NivelCreate, NivelResponse, NivelUpdate,
    PaisCreate, PaisResponse, PaisUpdate,
    SedeCreate, SedeResponse, SedeUpdate,
)
from app.services.location import LocationService

router = APIRouter()

WRITE = [Depends(require_admin)]


def get_service(db: AsyncSession = Depends(get_db)) -> LocationService:
    return LocationService(db)


def _ctx(request: Request, user: CurrentUser) -> dict:
    return {"usuario_id": user.USU_Usuario, "ip": get_client_ip(request)}


# ================= PAIS =================
@router.post("/paises", response_model=PaisResponse, status_code=201, dependencies=WRITE)
async def create_pais(schema: PaisCreate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.create_pais(schema, **_ctx(request, current_user))


@router.get("/paises", response_model=List[PaisResponse])
async def list_paises(service: LocationService = Depends(get_service)):
    return await service.list_paises()


@router.get("/paises/{id}", response_model=PaisResponse)
async def get_pais(id: int, service: LocationService = Depends(get_service)):
    return await service.get_pais(id)


@router.patch("/paises/{id}", response_model=PaisResponse, dependencies=WRITE)
async def update_pais(id: int, schema: PaisUpdate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.update_pais(id, schema, **_ctx(request, current_user))


@router.delete("/paises/{id}", status_code=204, dependencies=WRITE)
async def delete_pais(id: int, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    await service.delete_pais(id, **_ctx(request, current_user))


# ================= ESTADO =================
@router.post("/estados", response_model=EstadoResponse, status_code=201, dependencies=WRITE)
async def create_estado(schema: EstadoCreate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.create_estado(schema, **_ctx(request, current_user))


@router.get("/estados", response_model=List[EstadoResponse])
async def list_estados(pais_id: int = Query(...), service: LocationService = Depends(get_service)):
    return await service.list_estados(pais_id)


@router.get("/estados/{id}", response_model=EstadoResponse)
async def get_estado(id: int, service: LocationService = Depends(get_service)):
    return await service.get_estado(id)


@router.patch("/estados/{id}", response_model=EstadoResponse, dependencies=WRITE)
async def update_estado(id: int, schema: EstadoUpdate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.update_estado(id, schema, **_ctx(request, current_user))


@router.delete("/estados/{id}", status_code=204, dependencies=WRITE)
async def delete_estado(id: int, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    await service.delete_estado(id, **_ctx(request, current_user))


# ================= MUNICIPIO =================
@router.post("/municipios", response_model=MunicipioResponse, status_code=201, dependencies=WRITE)
async def create_municipio(schema: MunicipioCreate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.create_municipio(schema, **_ctx(request, current_user))


@router.get("/municipios", response_model=List[MunicipioResponse])
async def list_municipios(estado_id: int = Query(...), service: LocationService = Depends(get_service)):
    return await service.list_municipios(estado_id)


@router.get("/municipios/{id}", response_model=MunicipioResponse)
async def get_municipio(id: int, service: LocationService = Depends(get_service)):
    return await service.get_municipio(id)


@router.patch("/municipios/{id}", response_model=MunicipioResponse, dependencies=WRITE)
async def update_municipio(id: int, schema: MunicipioUpdate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.update_municipio(id, schema, **_ctx(request, current_user))


@router.delete("/municipios/{id}", status_code=204, dependencies=WRITE)
async def delete_municipio(id: int, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    await service.delete_municipio(id, **_ctx(request, current_user))


# ================= SEDE =================
@router.post("/sedes", response_model=SedeResponse, status_code=201, dependencies=WRITE)
async def create_sede(schema: SedeCreate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.create_sede(schema, **_ctx(request, current_user))


@router.get("/sedes", response_model=List[SedeResponse])
async def list_sedes(municipio_id: int = Query(...), service: LocationService = Depends(get_service)):
    return await service.list_sedes(municipio_id)


@router.get("/sedes/{id}", response_model=SedeResponse)
async def get_sede(id: int, service: LocationService = Depends(get_service)):
    return await service.get_sede(id)


@router.patch("/sedes/{id}", response_model=SedeResponse, dependencies=WRITE)
async def update_sede(id: int, schema: SedeUpdate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.update_sede(id, schema, **_ctx(request, current_user))


@router.delete("/sedes/{id}", status_code=204, dependencies=WRITE)
async def delete_sede(id: int, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    await service.delete_sede(id, **_ctx(request, current_user))


# ================= EDIFICIO =================
@router.post("/edificios", response_model=EdificioResponse, status_code=201, dependencies=WRITE)
async def create_edificio(schema: EdificioCreate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.create_edificio(schema, **_ctx(request, current_user))


@router.get("/edificios", response_model=List[EdificioResponse])
async def list_edificios(sede_id: int = Query(...), service: LocationService = Depends(get_service)):
    return await service.list_edificios(sede_id)


@router.get("/edificios/{id}", response_model=EdificioResponse)
async def get_edificio(id: int, service: LocationService = Depends(get_service)):
    return await service.get_edificio(id)


@router.patch("/edificios/{id}", response_model=EdificioResponse, dependencies=WRITE)
async def update_edificio(id: int, schema: EdificioUpdate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.update_edificio(id, schema, **_ctx(request, current_user))


@router.delete("/edificios/{id}", status_code=204, dependencies=WRITE)
async def delete_edificio(id: int, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    await service.delete_edificio(id, **_ctx(request, current_user))


# ================= NIVEL =================
@router.post("/niveles", response_model=NivelResponse, status_code=201, dependencies=WRITE)
async def create_nivel(schema: NivelCreate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.create_nivel(schema, **_ctx(request, current_user))


@router.get("/niveles", response_model=List[NivelResponse])
async def list_niveles(edificio_id: int = Query(...), service: LocationService = Depends(get_service)):
    return await service.list_niveles(edificio_id)


@router.get("/niveles/{id}", response_model=NivelResponse)
async def get_nivel(id: int, service: LocationService = Depends(get_service)):
    return await service.get_nivel(id)


@router.patch("/niveles/{id}", response_model=NivelResponse, dependencies=WRITE)
async def update_nivel(id: int, schema: NivelUpdate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.update_nivel(id, schema, **_ctx(request, current_user))


@router.delete("/niveles/{id}", status_code=204, dependencies=WRITE)
async def delete_nivel(id: int, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    await service.delete_nivel(id, **_ctx(request, current_user))


# ================= AREA =================
@router.get("/areas/all")
async def list_all_areas_jerarquico(db = Depends(get_db)):
    """
    Lista TODAS las áreas con su ruta jerárquica completa
    (Sede > Edificio > Nivel > Área). Útil para selectores planos.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.location import Area, Edificio, Nivel, Sede

    q = (
        select(Area)
        .options(
            selectinload(Area.nivel).selectinload(Nivel.edificio).selectinload(Edificio.sede)
        )
        .order_by(Area.ARE_Nombre)
    )
    result = await db.execute(q)
    rows = result.scalars().all()
    out = []
    for a in rows:
        nivel = a.nivel
        edificio = nivel.edificio if nivel else None
        sede = edificio.sede if edificio else None
        path_parts = [
            sede.SED_Nombre if sede else None,
            edificio.EDI_Nombre if edificio else None,
            f"Piso {nivel.NIV_Numero_Piso}" if nivel else None,
            a.ARE_Nombre,
        ]
        out.append({
            "ARE_Area": a.ARE_Area,
            "ARE_Nombre": a.ARE_Nombre,
            "ARE_Tipo_Acceso": a.ARE_Tipo_Acceso,
            "NIV_Nivel": a.NIV_Nivel,
            "ruta": " › ".join(p for p in path_parts if p),
        })
    return out


@router.post("/areas", response_model=AreaResponse, status_code=201, dependencies=WRITE)
async def create_area(schema: AreaCreate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.create_area(schema, **_ctx(request, current_user))


@router.get("/areas", response_model=List[AreaResponse])
async def list_areas(nivel_id: int = Query(...), service: LocationService = Depends(get_service)):
    return await service.list_areas(nivel_id)


@router.get("/areas/{id}", response_model=AreaResponse)
async def get_area(id: int, service: LocationService = Depends(get_service)):
    return await service.get_area(id)


@router.patch("/areas/{id}", response_model=AreaResponse, dependencies=WRITE)
async def update_area(id: int, schema: AreaUpdate, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    return await service.update_area(id, schema, **_ctx(request, current_user))


@router.delete("/areas/{id}", status_code=204, dependencies=WRITE)
async def delete_area(id: int, request: Request, current_user: CurrentUser, service: LocationService = Depends(get_service)):
    await service.delete_area(id, **_ctx(request, current_user))
