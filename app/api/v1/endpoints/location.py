from typing import List
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.location import LocationService
from app.schemas.location import (
    PaisCreate, PaisResponse, 
    EstadoCreate, EstadoResponse,
    MunicipioCreate, MunicipioResponse,
    SedeCreate, SedeResponse,
    EdificioCreate, EdificioResponse,
    NivelCreate, NivelResponse,
    AreaCreate, AreaResponse
)

router = APIRouter()

def get_service(db: AsyncSession = Depends(get_db)) -> LocationService:
    return LocationService(db)

# ================= PAIS =================
@router.post("/paises", response_model=PaisResponse, status_code=status.HTTP_201_CREATED)
async def create_pais(schema: PaisCreate, service: LocationService = Depends(get_service)):
    return await service.create_pais(schema)

@router.get("/paises", response_model=List[PaisResponse])
async def list_paises(service: LocationService = Depends(get_service)):
    return await service.list_paises()

# ================= ESTADO =================
@router.post("/estados", response_model=EstadoResponse, status_code=status.HTTP_201_CREATED)
async def create_estado(schema: EstadoCreate, service: LocationService = Depends(get_service)):
    return await service.create_estado(schema)

@router.get("/estados", response_model=List[EstadoResponse])
async def list_estados(pais_id: int = Query(..., description="ID del País"), service: LocationService = Depends(get_service)):
    return await service.list_estados(pais_id)

# ================= MUNICIPIO =================
@router.post("/municipios", response_model=MunicipioResponse, status_code=status.HTTP_201_CREATED)
async def create_municipio(schema: MunicipioCreate, service: LocationService = Depends(get_service)):
    return await service.create_municipio(schema)

@router.get("/municipios", response_model=List[MunicipioResponse])
async def list_municipios(estado_id: int = Query(..., description="ID del Estado"), service: LocationService = Depends(get_service)):
    return await service.list_municipios(estado_id)

# ================= SEDE =================
@router.post("/sedes", response_model=SedeResponse, status_code=status.HTTP_201_CREATED)
async def create_sede(schema: SedeCreate, service: LocationService = Depends(get_service)):
    return await service.create_sede(schema)

@router.get("/sedes", response_model=List[SedeResponse])
async def list_sedes(municipio_id: int = Query(..., description="ID del Municipio"), service: LocationService = Depends(get_service)):
    return await service.list_sedes(municipio_id)

# ================= EDIFICIO =================
@router.post("/edificios", response_model=EdificioResponse, status_code=status.HTTP_201_CREATED)
async def create_edificio(schema: EdificioCreate, service: LocationService = Depends(get_service)):
    return await service.create_edificio(schema)

@router.get("/edificios", response_model=List[EdificioResponse])
async def list_edificios(sede_id: int = Query(..., description="ID de la Sede"), service: LocationService = Depends(get_service)):
    return await service.list_edificios(sede_id)

# ================= NIVEL =================
@router.post("/niveles", response_model=NivelResponse, status_code=status.HTTP_201_CREATED)
async def create_nivel(schema: NivelCreate, service: LocationService = Depends(get_service)):
    return await service.create_nivel(schema)

@router.get("/niveles", response_model=List[NivelResponse])
async def list_niveles(edificio_id: int = Query(..., description="ID del Edificio"), service: LocationService = Depends(get_service)):
    return await service.list_niveles(edificio_id)

# ================= AREA =================
@router.post("/areas", response_model=AreaResponse, status_code=status.HTTP_201_CREATED)
async def create_area(schema: AreaCreate, service: LocationService = Depends(get_service)):
    return await service.create_area(schema)

@router.get("/areas", response_model=List[AreaResponse])
async def list_areas(nivel_id: int = Query(..., description="ID del Nivel"), service: LocationService = Depends(get_service)):
    return await service.list_areas(nivel_id)