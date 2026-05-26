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


@pytest_asyncio.fixture(scope="function")
async def engine():
    # Cada test arranca con DB limpia en memoria.
    e = create_async_engine("sqlite+aiosqlite:///:memory:", future=True, echo=False)
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
