"""Fixtures pytest. Usa SQLite en memoria para tests rápidos."""
import os
# Forzar configuración de tests ANTES de cualquier import de app.*.
# Asignación directa (no setdefault) para sobrescribir lo que venga de docker-compose.
os.environ["POSTGRES_SERVER"] = "sqlite"
os.environ["POSTGRES_USER"] = "test"
os.environ["POSTGRES_PASSWORD"] = "test"
os.environ["POSTGRES_DB"] = "test"
os.environ["SECRET_KEY"] = "test_secret_key_for_unit_tests_only_at_least_32_chars_long"
os.environ["ENVIRONMENT"] = "development"
os.environ["DEBUG"] = "false"
os.environ["DB_ECHO"] = "false"
os.environ["RATE_LIMIT_LOGIN"] = "10000/minute"
os.environ["RATE_LIMIT_DEFAULT"] = "100000/minute"
# Desactivar Redis en tests: el container puede tenerlo configurado, pero pytest
# no debe intentar hablar con un loop muerto. cache_get/set son no-op si REDIS_URL=""
os.environ["REDIS_URL"] = ""
# Adjuntos: dirigir el almacenamiento a un directorio temporal aislado para no
# escribir en /app/uploads durante los tests.
import tempfile as _tempfile
os.environ["UPLOAD_DIR"] = _tempfile.mkdtemp(prefix="lombardi_uploads_")
# Throttle de reset por cuenta desactivado por defecto en tests (los tests que
# lo ejercen lo activan vía monkeypatch). Así los demás no chocan con la ventana.
os.environ["PASSWORD_RESET_REQUEST_COOLDOWN_MINUTES"] = "0"

import asyncio
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """
    El limiter usa storage en memoria que persiste ENTRE tests dentro de la
    misma sesión de pytest. Sin resetear, los endpoints con límite literal
    (p.ej. /me/password '5/minute') acumulan llamadas a lo largo de la suite y
    fallan con 429. Lo limpiamos antes de cada test para aislarlos.
    """
    try:
        from app.core.limiter import limiter
        limiter.reset()
    except Exception:  # noqa: BLE001
        pass
    yield


@pytest_asyncio.fixture(scope="function")
async def engine():
    # Cada test arranca con DB limpia en memoria.
    e = create_async_engine("sqlite+aiosqlite:///:memory:", future=True, echo=False)

    # SQLite NO aplica claves foráneas por defecto. Lo activamos para que los
    # tests reflejen el comportamiento de Postgres (FK RESTRICT → IntegrityError
    # → 409 al borrar registros en uso, etc.).
    from sqlalchemy import event

    @event.listens_for(e.sync_engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield e
    await e.dispose()


@pytest_asyncio.fixture(scope="function")
async def session(engine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s


@pytest_asyncio.fixture(scope="function")
async def client(engine) -> AsyncIterator[AsyncClient]:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def sa_user(session):
    """Crea un usuario sa SUPER_ADMIN con password conocida."""
    from app.core.security import get_password_hash
    from app.models.organization import Cargo, Departamento, Persona, Usuario

    dep = Departamento(DEP_Nombre="SysAdmin")
    car = Cargo(CAR_Nombre="SysAdmin")
    session.add_all([dep, car])
    await session.flush()
    persona = Persona(
        PER_Primer_Nombre="System", PER_Primer_Apellido="Admin",
        PER_Email_Corporativo="admin@test.local",
        DEP_Departamento=dep.DEP_Departamento, CAR_Cargo=car.CAR_Cargo,
    )
    session.add(persona)
    await session.flush()
    user = Usuario(
        USU_Username="sa", USU_Password_Hash=get_password_hash("TestPassw0rd!"),
        USU_Rol="SUPER_ADMIN", PER_Persona=persona.PER_Persona,
    )
    session.add(user)
    await session.commit()
    return user


@pytest_asyncio.fixture
async def auth_token(client, sa_user):
    """Login y devuelve el access_token del sa."""
    r = await client.post(
        "/api/v1/login/access-token",
        data={"username": "sa", "password": "TestPassw0rd!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest_asyncio.fixture
async def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


# =========================================================================
# FIXTURES RICAS: catálogos completos para tests de flujo (asignación,
# offboarding, transición de estados, exports). Reflejan el mismo dominio
# que el seed_demo para que los tests cubran rutas reales del sistema.
# =========================================================================
@pytest_asyncio.fixture
async def domain_seed(session, sa_user):
    """
    Carga catálogos mínimos para tests de flujo:
      - TipoActivo: Laptop, Desktop, Monitor
      - Marca + Modelo
      - EstadoOperativo: Disponible(1), Asignado(2), En Reparación(3), Baja(4), En Bodega(5)
      - TipoMovimiento: Ingreso(1), Asignación(2), Devolución(3), Préstamo(4), Transferencia(5)
      - Ubicación: País → Estado → Municipio → Sede → Edificio → Nivel → Area
      - 2 Personas (alice, bob) en mismo depto, con cargo
      - 2 Activos: LAP-001 (Disponible), LAP-002 (En Bodega)

    Devuelve un dict con todos los ids/uuids para que el test los referencie
    sin hacer queries adicionales.
    """
    from app.models.catalogs import (
        TipoActivo, Marca, Modelo, EstadoOperativo,
    )
    from app.models.core import Activo
    from app.models.location import Pais, Estado as Edo, Municipio, Sede, Edificio, Nivel, Area
    from app.models.organization import Cargo, Departamento, Persona
    from app.models.traceability import TipoMovimiento
    from datetime import date

    # Catálogos técnicos
    tac_lap = TipoActivo(TAC_Nombre="Laptop", TAC_Prefijo="LAP")
    tac_dsk = TipoActivo(TAC_Nombre="Desktop", TAC_Prefijo="DSK")
    tac_mon = TipoActivo(TAC_Nombre="Monitor", TAC_Prefijo="MON")
    mar = Marca(MAR_Nombre="TestVendor")
    session.add_all([tac_lap, tac_dsk, tac_mon, mar])
    await session.flush()

    mod = Modelo(MOD_Nombre="Model-X", MAR_Marca=mar.MAR_Marca, MOD_Anio_Lanzamiento=2024)
    session.add(mod)
    await session.flush()

    # Estados Operativos — IDs explícitos para que el matching ilike funcione
    eop_disp = EstadoOperativo(EOP_Nombre="Disponible")
    eop_asig = EstadoOperativo(EOP_Nombre="Asignado")
    eop_rep = EstadoOperativo(EOP_Nombre="En Reparación")
    eop_baja = EstadoOperativo(EOP_Nombre="Baja")
    eop_bod = EstadoOperativo(EOP_Nombre="En Bodega")
    session.add_all([eop_disp, eop_asig, eop_rep, eop_baja, eop_bod])
    await session.flush()

    # Tipos de movimiento
    tmo_in = TipoMovimiento(TMO_Nombre="Ingreso")
    tmo_asg = TipoMovimiento(TMO_Nombre="Asignación")
    tmo_dev = TipoMovimiento(TMO_Nombre="Devolución")
    tmo_pres = TipoMovimiento(TMO_Nombre="Préstamo")
    tmo_tra = TipoMovimiento(TMO_Nombre="Transferencia")
    session.add_all([tmo_in, tmo_asg, tmo_dev, tmo_pres, tmo_tra])
    await session.flush()

    # Ubicación
    pais = Pais(PAI_Nombre="México", PAI_Codigo_ISO="MX")
    session.add(pais); await session.flush()
    edo = Edo(EST_Nombre="Jalisco", PAI_Pais=pais.PAI_Pais)
    session.add(edo); await session.flush()
    muni = Municipio(MUN_Nombre="Guadalajara", EST_Estado=edo.EST_Estado)
    session.add(muni); await session.flush()
    sede = Sede(SED_Nombre="Oficina GDL", MUN_Municipio=muni.MUN_Municipio)
    session.add(sede); await session.flush()
    edif = Edificio(EDI_Nombre="Edificio A", SED_Sede=sede.SED_Sede)
    session.add(edif); await session.flush()
    niv = Nivel(NIV_Numero_Piso=1, EDI_Edificio=edif.EDI_Edificio)
    session.add(niv); await session.flush()
    area = Area(ARE_Nombre="TI", NIV_Nivel=niv.NIV_Nivel)
    session.add(area); await session.flush()

    # Organización: cargo + depto reutilizable
    dep = Departamento(DEP_Nombre="Tecnología")
    car = Cargo(CAR_Nombre="Ingeniero")
    session.add_all([dep, car]); await session.flush()

    alice = Persona(
        PER_Primer_Nombre="Alice", PER_Primer_Apellido="Test",
        PER_Email_Corporativo="alice@test.local",
        DEP_Departamento=dep.DEP_Departamento, CAR_Cargo=car.CAR_Cargo,
    )
    bob = Persona(
        PER_Primer_Nombre="Bob", PER_Primer_Apellido="Test",
        PER_Email_Corporativo="bob@test.local",
        DEP_Departamento=dep.DEP_Departamento, CAR_Cargo=car.CAR_Cargo,
    )
    session.add_all([alice, bob])
    await session.flush()

    # Activos: uno disponible, uno en bodega
    act_1 = Activo(
        ACT_Codigo_Interno="LAP-001",
        ACT_Serie_Fabricante="SER-001",
        ACT_Hostname="laptop-1",
        ACT_Fecha_Compra=date(2024, 1, 1),
        MOD_Modelo=mod.MOD_Modelo,
        TAC_Tipo_Activo=tac_lap.TAC_Tipo_Activo,
        EOP_Estado_Operativo=eop_disp.EOP_Estado_Operativo,
    )
    act_2 = Activo(
        ACT_Codigo_Interno="LAP-002",
        ACT_Serie_Fabricante="SER-002",
        ACT_Fecha_Compra=date(2024, 2, 1),
        MOD_Modelo=mod.MOD_Modelo,
        TAC_Tipo_Activo=tac_lap.TAC_Tipo_Activo,
        EOP_Estado_Operativo=eop_bod.EOP_Estado_Operativo,
    )
    session.add_all([act_1, act_2])
    await session.commit()

    return {
        "tac_lap": tac_lap.TAC_Tipo_Activo,
        "tac_dsk": tac_dsk.TAC_Tipo_Activo,
        "tac_mon": tac_mon.TAC_Tipo_Activo,
        "mar": mar.MAR_Marca,
        "mod": mod.MOD_Modelo,
        "eop_disp": eop_disp.EOP_Estado_Operativo,
        "eop_asig": eop_asig.EOP_Estado_Operativo,
        "eop_rep": eop_rep.EOP_Estado_Operativo,
        "eop_baja": eop_baja.EOP_Estado_Operativo,
        "eop_bod": eop_bod.EOP_Estado_Operativo,
        "tmo_in": tmo_in.TMO_Tipo_Movimiento,
        "tmo_asg": tmo_asg.TMO_Tipo_Movimiento,
        "tmo_dev": tmo_dev.TMO_Tipo_Movimiento,
        "tmo_pres": tmo_pres.TMO_Tipo_Movimiento,
        "tmo_tra": tmo_tra.TMO_Tipo_Movimiento,
        "area": area.ARE_Area,
        "alice": str(alice.PER_Persona),
        "bob": str(bob.PER_Persona),
        "act_1": str(act_1.ACT_Activo),  # Disponible
        "act_2": str(act_2.ACT_Activo),  # En Bodega
    }


@pytest_asyncio.fixture
async def software_seed(session, domain_seed):
    """Catálogo de software/licencias + tipos de mantenimiento."""
    from app.models.traceability import TipoMantenimiento
    from app.models.software import Software, Licencia, TipoLicencia

    tli = TipoLicencia(TLI_Nombre="Volumen")
    sof = Software(SOF_Nombre="Office 365", SOF_Version="2024", SOF_Fabricante="Microsoft")
    session.add_all([tli, sof])
    await session.flush()

    lic = Licencia(
        SOF_Software=sof.SOF_Software,
        TLI_Tipo_Licencia=tli.TLI_Tipo_Licencia,
        LIC_Cantidad_Total=5,
        LIC_Cantidad_Usada=0,
    )
    session.add(lic)

    tma_corr = TipoMantenimiento(TMA_Nombre="Correctivo")
    tma_prev = TipoMantenimiento(TMA_Nombre="Preventivo")
    session.add_all([tma_corr, tma_prev])
    await session.commit()

    return {
        **domain_seed,
        "sof": sof.SOF_Software,
        "lic": lic.LIC_Licencia,
        "tma_corr": tma_corr.TMA_Tipo_Mantenimiento,
        "tma_prev": tma_prev.TMA_Tipo_Mantenimiento,
    }
