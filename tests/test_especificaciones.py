"""Tests del CRUD de características/especificaciones por activo (RAM, disco…)."""
import pytest


@pytest.mark.asyncio
async def test_especificaciones_crud(client, auth_headers, domain_seed, session):
    from app.models.catalogs import TipoEspecificacion
    tes = TipoEspecificacion(TES_Nombre="RAM-test", TES_Unidad_Medida="GB")
    session.add(tes)
    await session.commit()
    act = domain_seed["act_1"]

    # CREATE → 201 + respuesta enriquecida (nombre + unidad)
    r = await client.post(
        f"/api/v1/core/activos/{act}/especificaciones", headers=auth_headers,
        json={"TES_Tipo_Especificacion": tes.TES_Tipo_Especificacion, "ESP_Valor": "16"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["TES_Nombre"] == "RAM-test"
    assert body["TES_Unidad_Medida"] == "GB"
    assert body["ESP_Valor"] == "16"
    esp_id = body["ESP_Especificacion"]

    # LIST
    lst = await client.get(f"/api/v1/core/activos/{act}/especificaciones", headers=auth_headers)
    assert lst.status_code == 200
    assert any(s["ESP_Valor"] == "16" for s in lst.json())

    # UPDATE valor
    up = await client.patch(
        f"/api/v1/core/especificaciones/{esp_id}", headers=auth_headers, json={"ESP_Valor": "32"})
    assert up.status_code == 204

    # DUPLICADO (mismo tipo en el mismo activo) → 409
    dup = await client.post(
        f"/api/v1/core/activos/{act}/especificaciones", headers=auth_headers,
        json={"TES_Tipo_Especificacion": tes.TES_Tipo_Especificacion, "ESP_Valor": "8"})
    assert dup.status_code == 409

    # DELETE
    d = await client.delete(f"/api/v1/core/especificaciones/{esp_id}", headers=auth_headers)
    assert d.status_code == 204
    lst2 = await client.get(f"/api/v1/core/activos/{act}/especificaciones", headers=auth_headers)
    assert lst2.json() == []


@pytest.mark.asyncio
async def test_add_especificacion_requires_operativo(client, domain_seed, session, sa_user):
    """Un CONSULTA no puede agregar características."""
    # Crear un CONSULTA y loguear
    import uuid
    from sqlalchemy import select
    from app.models.organization import Persona
    alice = (await session.execute(
        select(Persona).where(Persona.PER_Persona == uuid.UUID(domain_seed["alice"])))).scalar_one()
    p = Persona(PER_Primer_Nombre="Con", PER_Primer_Apellido="Sulta",
                PER_Email_Corporativo="consulta@example.com",
                DEP_Departamento=alice.DEP_Departamento, CAR_Cargo=alice.CAR_Cargo)
    session.add(p)
    await session.commit()
    # sa crea el CONSULTA
    sa_headers = {"Authorization": f"Bearer {await _token(client)}"}
    await client.post("/api/v1/org/usuarios", headers=sa_headers, json={
        "USU_Username": "cons_spec", "USU_Password": "Consulta#2026",
        "USU_Rol": "CONSULTA", "PER_Persona": str(p.PER_Persona)})
    lr = await client.post("/api/v1/login/access-token",
        data={"username": "cons_spec", "password": "Consulta#2026"},
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    con = {"Authorization": f"Bearer {lr.json()['access_token']}"}
    r = await client.post(f"/api/v1/core/activos/{domain_seed['act_1']}/especificaciones",
        headers=con, json={"TES_Tipo_Especificacion": 1, "ESP_Valor": "x"})
    assert r.status_code == 403


async def _token(client):
    r = await client.post("/api/v1/login/access-token",
        data={"username": "sa", "password": "TestPassw0rd!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    return r.json()["access_token"]
