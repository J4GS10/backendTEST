"""
Tests del flujo software/licencias/instalaciones.

Garantías:
  - Instalar licencia incrementa LIC_Cantidad_Usada.
  - Desinstalar decrementa LIC_Cantidad_Usada.
  - Idempotency-Key permite reintentos sin duplicar la instalación.
  - No se puede instalar si LIC_Cantidad_Usada >= LIC_Cantidad_Total.
  - No se puede instalar 2 veces la misma licencia en el mismo activo.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.software import Licencia, LicenciaClave, Instalacion


def _u(v):
    return uuid.UUID(v) if isinstance(v, str) else v


@pytest.mark.asyncio
async def test_instalar_licencia_incrementa_uso(client, auth_headers, software_seed, session):
    s = software_seed
    r = await client.post(
        "/api/v1/soft/instalaciones",
        json={
            "ACT_Activo": s["act_1"],
            "LIC_Licencia": s["lic"],
            "INS_Fecha_Instalacion": "2026-05-28",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    session.expire_all()
    lic = (await session.execute(
        select(Licencia).where(Licencia.LIC_Licencia == s["lic"])
    )).scalar_one()
    assert lic.LIC_Cantidad_Usada == 1


@pytest.mark.asyncio
async def test_desinstalar_decrementa_uso(client, auth_headers, software_seed, session):
    s = software_seed
    payload = {
        "ACT_Activo": s["act_1"],
        "LIC_Licencia": s["lic"],
        "INS_Fecha_Instalacion": "2026-05-28",
    }
    await client.post("/api/v1/soft/instalaciones", json=payload, headers=auth_headers)
    r = await client.post(
        "/api/v1/soft/instalaciones/desinstalar", json=payload, headers=auth_headers,
    )
    assert r.status_code == 200
    session.expire_all()
    lic = (await session.execute(
        select(Licencia).where(Licencia.LIC_Licencia == s["lic"])
    )).scalar_one()
    assert lic.LIC_Cantidad_Usada == 0


@pytest.mark.asyncio
async def test_idempotency_key_no_duplica_instalacion(
    client, auth_headers, software_seed, session,
):
    """Re-enviar el mismo POST con la misma Idempotency-Key NO debe crear 2 filas."""
    s = software_seed
    key = "abcdef1234567890ABCDEF"  # cumple regex ^[A-Za-z0-9_-]{16,128}$
    payload = {
        "ACT_Activo": s["act_1"],
        "LIC_Licencia": s["lic"],
        "INS_Fecha_Instalacion": "2026-05-28",
    }
    h = {**auth_headers, "Idempotency-Key": key}
    r1 = await client.post("/api/v1/soft/instalaciones", json=payload, headers=h)
    r2 = await client.post("/api/v1/soft/instalaciones", json=payload, headers=h)
    assert r1.status_code == 201
    # Segundo request retorna 201 (cached) con el mismo INS_Instalacion.
    assert r2.status_code == 201
    assert r1.json()["INS_Instalacion"] == r2.json()["INS_Instalacion"]

    session.expire_all()
    rows = (await session.execute(
        select(Instalacion).where(
            Instalacion.ACT_Activo == _u(s["act_1"]),
            Instalacion.LIC_Licencia == s["lic"],
        )
    )).scalars().all()
    # Una sola fila de instalación.
    assert len([r for r in rows if r.INS_Estado]) == 1


@pytest.mark.asyncio
async def test_no_se_puede_exceder_cantidad_total_licencia(
    client, auth_headers, software_seed, session,
):
    """La licencia tiene LIC_Cantidad_Total=5. Pre-llenar a 5 y verificar
    que la siguiente instalación falla."""
    from sqlalchemy import update
    s = software_seed
    await session.execute(
        update(Licencia)
        .where(Licencia.LIC_Licencia == s["lic"])
        .values(LIC_Cantidad_Usada=5)
    )
    await session.commit()

    r = await client.post(
        "/api/v1/soft/instalaciones",
        json={
            "ACT_Activo": s["act_1"],
            "LIC_Licencia": s["lic"],
            "INS_Fecha_Instalacion": "2026-05-28",
        },
        headers=auth_headers,
    )
    assert r.status_code in (400, 409)
    detail = r.json()["detail"]
    assert "LICEN" in detail.upper() or "SOLD_OUT" in detail.upper() or "FULL" in detail.upper()


@pytest.mark.asyncio
async def test_no_duplicar_licencia_en_mismo_activo(
    client, auth_headers, software_seed,
):
    """Instalar la misma LIC en el mismo activo dos veces debe fallar."""
    s = software_seed
    payload = {
        "ACT_Activo": s["act_1"],
        "LIC_Licencia": s["lic"],
        "INS_Fecha_Instalacion": "2026-05-28",
    }
    r1 = await client.post("/api/v1/soft/instalaciones", json=payload, headers=auth_headers)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/soft/instalaciones", json=payload, headers=auth_headers)
    # Sin Idempotency-Key, el segundo intento debería fallar por duplicado activo.
    assert r2.status_code in (400, 409)


@pytest.mark.asyncio
async def test_instalar_licencia_a_persona_incrementa_uso(
    client, auth_headers, software_seed, session,
):
    """Las licencias tambien pueden asignarse a empleados, no solo a activos."""
    s = software_seed
    payload = {
        "PER_Persona": s["alice"],
        "LIC_Licencia": s["lic"],
        "INS_Fecha_Instalacion": "2026-05-28",
    }

    r = await client.post("/api/v1/soft/instalaciones", json=payload, headers=auth_headers)
    assert r.status_code == 201, r.text
    assert r.json()["PER_Persona"] == s["alice"]
    assert r.json()["ACT_Activo"] is None

    session.expire_all()
    lic = (await session.execute(
        select(Licencia).where(Licencia.LIC_Licencia == s["lic"])
    )).scalar_one()
    assert lic.LIC_Cantidad_Usada == 1


@pytest.mark.asyncio
async def test_licencia_con_claves_reserva_y_libera_key(
    client, auth_headers, software_seed, session,
):
    s = software_seed
    r = await client.post("/api/v1/soft/licencias", headers=auth_headers, json={
        "SOF_Software": s["sof"],
        "TLI_Tipo_Licencia": s["tli"],
        "LIC_Cantidad_Total": 2,
        "LIC_Claves": [
            {"LCL_Clave_Activacion": "KEY-SW-IND-001"},
            {"LCL_Clave_Activacion": "KEY-SW-IND-002"},
        ],
    })
    assert r.status_code == 201, r.text
    lic_id = r.json()["LIC_Licencia"]
    assert r.json()["LIC_Claves_Disponibles"] == 2

    payload = {
        "ACT_Activo": s["act_1"],
        "LIC_Licencia": lic_id,
        "INS_Fecha_Instalacion": "2026-05-28",
    }
    inst = await client.post("/api/v1/soft/instalaciones", json=payload, headers=auth_headers)
    assert inst.status_code == 201, inst.text
    key_id = inst.json()["LCL_Licencia_Clave"]
    assert key_id is not None

    keys = await client.get(f"/api/v1/soft/licencias/{lic_id}/claves", headers=auth_headers)
    assert keys.status_code == 200, keys.text
    assigned_key = next(k for k in keys.json() if k["LCL_Licencia_Clave"] == key_id)
    assert assigned_key["LCL_Clave_Activacion"] == "KEY-SW-IND-001"
    assert assigned_key["LCL_Estado"] == "ASIGNADA"
    assert assigned_key["LCL_Destino_Tipo"] == "ACTIVO"
    assert assigned_key["LCL_Destino_Id"] == s["act_1"]
    assert assigned_key["LCL_Destino_Nombre"]
    assert assigned_key["LCL_Asignada_En"] == "2026-05-28"

    session.expire_all()
    clave = (await session.execute(
        select(LicenciaClave).where(LicenciaClave.LCL_Licencia_Clave == key_id)
    )).scalar_one()
    assert clave.LCL_Estado == "ASIGNADA"

    out = await client.post("/api/v1/soft/instalaciones/desinstalar", json=payload, headers=auth_headers)
    assert out.status_code == 200, out.text
    session.expire_all()
    clave = (await session.execute(
        select(LicenciaClave).where(LicenciaClave.LCL_Licencia_Clave == key_id)
    )).scalar_one()
    assert clave.LCL_Estado == "DISPONIBLE"

    keys_after = await client.get(f"/api/v1/soft/licencias/{lic_id}/claves", headers=auth_headers)
    assert keys_after.status_code == 200, keys_after.text
    released_key = next(k for k in keys_after.json() if k["LCL_Licencia_Clave"] == key_id)
    assert released_key["LCL_Estado"] == "DISPONIBLE"
    assert released_key["LCL_Destino_Tipo"] is None
    assert released_key["LCL_Destino_Nombre"] is None


@pytest.mark.asyncio
async def test_claves_no_salen_en_listado_general_y_requieren_admin(
    client, auth_headers, software_seed, session,
):
    from app.core.security import get_password_hash
    from app.models.governance import AuditoriaSistema
    from app.models.organization import Cargo, Departamento, Persona, Usuario

    dep = Departamento(DEP_Nombre="Mesa de ayuda")
    car = Cargo(CAR_Nombre="Tecnico QA")
    session.add_all([dep, car])
    await session.flush()
    per = Persona(
        PER_Primer_Nombre="Tecnico",
        PER_Primer_Apellido="Uno",
        PER_Email_Corporativo="tecnico@test.local",
        DEP_Departamento=dep.DEP_Departamento,
        CAR_Cargo=car.CAR_Cargo,
    )
    session.add(per)
    await session.flush()
    session.add(Usuario(
        USU_Username="tecnico_keys",
        USU_Password_Hash=get_password_hash("TestPassw0rd!"),
        USU_Rol="TECNICO",
        PER_Persona=per.PER_Persona,
    ))
    await session.commit()

    tech_token = (await client.post(
        "/api/v1/login/access-token",
        data={"username": "tecnico_keys", "password": "TestPassw0rd!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )).json()["access_token"]
    tech_headers = {"Authorization": f"Bearer {tech_token}"}

    r = await client.post("/api/v1/soft/licencias", headers=auth_headers, json={
        "SOF_Software": software_seed["sof"],
        "TLI_Tipo_Licencia": software_seed["tli"],
        "LIC_Cantidad_Total": 1,
        "LIC_Clave_Activacion": "KEY-SENSITIVE-001",
    })
    assert r.status_code == 201, r.text
    lic_id = r.json()["LIC_Licencia"]
    assert r.json()["LIC_Clave_Activacion"] is None

    listado = await client.get(
        f"/api/v1/soft/licencias?software_id={software_seed['sof']}",
        headers=tech_headers,
    )
    assert listado.status_code == 200, listado.text
    assert "KEY-SENSITIVE-001" not in str(listado.json())
    creada = next(item for item in listado.json() if item["LIC_Licencia"] == lic_id)
    assert creada["LIC_Clave_Activacion"] is None
    assert creada["LIC_Claves_Total"] == 1

    denied = await client.get(f"/api/v1/soft/licencias/{lic_id}/claves", headers=tech_headers)
    assert denied.status_code == 403

    keys = await client.get(f"/api/v1/soft/licencias/{lic_id}/claves", headers=auth_headers)
    assert keys.status_code == 200, keys.text
    assert keys.json()[0]["LCL_Clave_Activacion"] == "KEY-SENSITIVE-001"

    audit = (await session.execute(
        select(AuditoriaSistema).where(
            AuditoriaSistema.AUD_Accion == "VIEW_KEYS",
            AuditoriaSistema.AUD_Entidad_Afectada == "INV_LICENCIA_CLAVE",
        )
    )).scalars().all()
    assert audit


@pytest.mark.asyncio
async def test_clave_legada_solo_se_expone_en_endpoint_auditado(
    client, auth_headers, software_seed, session,
):
    from app.core.security import encrypt_field

    legacy = Licencia(
        SOF_Software=software_seed["sof"],
        TLI_Tipo_Licencia=software_seed["tli"],
        LIC_Cantidad_Total=1,
        LIC_Cantidad_Usada=0,
        LIC_Clave_Activacion=encrypt_field("KEY-LEGACY-001"),
    )
    session.add(legacy)
    await session.commit()

    listado = await client.get(
        f"/api/v1/soft/licencias?software_id={software_seed['sof']}",
        headers=auth_headers,
    )
    assert listado.status_code == 200, listado.text
    assert "KEY-LEGACY-001" not in str(listado.json())
    row = next(item for item in listado.json() if item["LIC_Licencia"] == legacy.LIC_Licencia)
    assert row["LIC_Clave_Activacion"] is None
    assert row["LIC_Claves_Total"] == 1

    keys = await client.get(f"/api/v1/soft/licencias/{legacy.LIC_Licencia}/claves", headers=auth_headers)
    assert keys.status_code == 200, keys.text
    assert keys.json() == [{
        "LCL_Licencia_Clave": -legacy.LIC_Licencia,
        "LIC_Licencia": legacy.LIC_Licencia,
        "LCL_Clave_Activacion": "KEY-LEGACY-001",
        "LCL_Referencia": "Clave legada",
        "LCL_Estado": "DISPONIBLE",
        "LCL_Creado_En": None,
        "LCL_Asignada_En": None,
        "LCL_Destino_Tipo": None,
        "LCL_Destino_Id": None,
        "LCL_Destino_Nombre": None,
        "LCL_Destino_Detalle": None,
    }]


@pytest.mark.asyncio
async def test_no_duplicar_licencia_en_misma_persona(
    client, auth_headers, software_seed,
):
    """Una persona no puede consumir dos veces la misma licencia activa."""
    s = software_seed
    payload = {
        "PER_Persona": s["alice"],
        "LIC_Licencia": s["lic"],
        "INS_Fecha_Instalacion": "2026-05-28",
    }
    r1 = await client.post("/api/v1/soft/instalaciones", json=payload, headers=auth_headers)
    assert r1.status_code == 201, r1.text
    r2 = await client.post("/api/v1/soft/instalaciones", json=payload, headers=auth_headers)
    assert r2.status_code in (400, 409)


@pytest.mark.asyncio
async def test_instalacion_exige_un_solo_destino(client, auth_headers, software_seed):
    """La instalacion debe apuntar a activo o persona, nunca ambos."""
    s = software_seed
    r = await client.post(
        "/api/v1/soft/instalaciones",
        json={
            "ACT_Activo": s["act_1"],
            "PER_Persona": s["alice"],
            "LIC_Licencia": s["lic"],
            "INS_Fecha_Instalacion": "2026-05-28",
        },
        headers=auth_headers,
    )
    assert r.status_code == 422
