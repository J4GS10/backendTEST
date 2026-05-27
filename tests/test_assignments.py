"""
Tests del ciclo de vida de asignación de activos.

Cubre los métodos públicos que consume el frontend:
  - GET /trazabilidad/persona/{id}/asignaciones
  - GET /trazabilidad/activo/{id}/historial
  - POST /trazabilidad/movimientos
  - POST /trazabilidad/devolucion
  - POST /trazabilidad/transferencia
"""
import pytest


@pytest.mark.asyncio
async def test_listar_asignaciones_vigentes_persona(
    client, auth_headers, domain_seed,
):
    """Después de 2 asignaciones a alice, el endpoint las devuelve."""
    d = domain_seed
    for act_id in (d["act_1"], d["act_2"]):
        await client.post(
            "/api/v1/trazabilidad/movimientos",
            json={
                "ACT_Activo": act_id, "PER_Persona": d["alice"],
                "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
            },
            headers=auth_headers,
        )
    r = await client.get(
        f"/api/v1/trazabilidad/persona/{d['alice']}/asignaciones",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 2
    abiertos = [x for x in items if not x.get("MOV_Fecha_Devolucion")]
    assert len(abiertos) == 2


@pytest.mark.asyncio
async def test_historial_activo_incluye_movimientos_cerrados(
    client, auth_headers, domain_seed,
):
    """
    El historial de un activo muestra TODOS los movimientos: vigentes y
    cerrados. Después de asignar → devolver → re-asignar deberíamos ver 3 filas.
    """
    d = domain_seed
    # 1. asignar a alice
    await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_1"], "PER_Persona": d["alice"],
            "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
        },
        headers=auth_headers,
    )
    # 2. devolver
    await client.post(
        "/api/v1/trazabilidad/devolucion",
        json={"ACT_Activo": d["act_1"]},
        headers=auth_headers,
    )
    # 3. asignar a bob
    await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_1"], "PER_Persona": d["bob"],
            "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
        },
        headers=auth_headers,
    )

    r = await client.get(
        f"/api/v1/trazabilidad/activo/{d['act_1']}/historial",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    historial = r.json()
    assert len(historial) == 2  # 2 movimientos: el cerrado + el abierto
    cerrados = [h for h in historial if h.get("MOV_Fecha_Devolucion")]
    abiertos = [h for h in historial if not h.get("MOV_Fecha_Devolucion")]
    assert len(cerrados) == 1
    assert len(abiertos) == 1


@pytest.mark.asyncio
async def test_no_se_puede_transferir_activo_no_asignado(
    client, auth_headers, domain_seed,
):
    """Transferir un activo que no está asignado debe fallar 400."""
    d = domain_seed
    r = await client.post(
        "/api/v1/trazabilidad/transferencia",
        json={
            "ACT_Activo": d["act_1"],
            "PER_Persona_Destino": d["alice"],
            "ARE_Area_Destino": d["area"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "ASSET_IS_NOT_ASSIGNED_CANNOT_TRANSFER"


@pytest.mark.asyncio
async def test_movimiento_a_persona_inexistente_falla(
    client, auth_headers, domain_seed,
):
    """Asignar a una persona inexistente debe devolver 404."""
    import uuid
    d = domain_seed
    fake_uuid = str(uuid.uuid4())
    r = await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_1"], "PER_Persona": fake_uuid,
            "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "PERSON_NOT_FOUND"


@pytest.mark.asyncio
async def test_movimiento_a_activo_inexistente_falla(
    client, auth_headers, domain_seed,
):
    """Asignar un activo inexistente debe devolver 404."""
    import uuid
    d = domain_seed
    fake_uuid = str(uuid.uuid4())
    r = await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": fake_uuid, "PER_Persona": d["alice"],
            "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "ASSET_NOT_FOUND"
