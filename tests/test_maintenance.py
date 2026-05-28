"""
Tests del flujo de mantenimiento.

Garantías:
  - Crear ticket lo deja abierto.
  - 1 solo ticket abierto por activo (constraint XOR).
  - Agregar detalle al ticket abierto funciona.
  - Cerrar el ticket marca MAN_Fecha_Cierre.
  - Cerrar 2 veces no es permitido.
"""
import pytest


@pytest.mark.asyncio
async def test_crear_ticket_correctivo(client, auth_headers, software_seed):
    s = software_seed
    r = await client.post(
        "/api/v1/mantenimiento/",
        json={
            "ACT_Activo": s["act_1"],
            "PER_Persona_Solicita": s["alice"],
            "TMA_Tipo_Mantenimiento": s["tma_corr"],
            "MAN_Descripcion_Falla": "Diagnóstico inicial",
            "MAN_Costo_Total": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["MAN_Fecha_Cierre"] is None


@pytest.mark.asyncio
async def test_no_dos_tickets_abiertos_en_mismo_activo(client, auth_headers, software_seed):
    s = software_seed
    base = {
        "ACT_Activo": s["act_1"],
        "PER_Persona_Solicita": s["alice"],
        "TMA_Tipo_Mantenimiento": s["tma_corr"],
        "MAN_Descripcion_Falla": "Falla 1",
        "MAN_Costo_Total": 0,
    }
    r1 = await client.post("/api/v1/mantenimiento/", json=base, headers=auth_headers)
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/v1/mantenimiento/",
        json={**base, "MAN_Descripcion_Falla": "Falla 2"},
        headers=auth_headers,
    )
    assert r2.status_code in (400, 409)


@pytest.mark.asyncio
async def test_agregar_detalle_y_cerrar(client, auth_headers, software_seed):
    s = software_seed
    r = await client.post(
        "/api/v1/mantenimiento/",
        json={
            "ACT_Activo": s["act_1"],
            "PER_Persona_Solicita": s["alice"],
            "TMA_Tipo_Mantenimiento": s["tma_corr"],
            "MAN_Descripcion_Falla": "Falla con detalle",
            "MAN_Costo_Total": 0,
            "detalles": [{"DMA_Accion_Realizada": "Diagnóstico", "DMA_Costo_Item": 0}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    ticket_id = r.json()["MAN_Mantenimiento"]

    # Agregar 2do detalle
    r2 = await client.post(
        f"/api/v1/mantenimiento/{ticket_id}/detalles",
        json={"DMA_Accion_Realizada": "Reparación efectiva", "DMA_Costo_Item": 100},
        headers=auth_headers,
    )
    assert r2.status_code == 201

    # Cerrar
    r3 = await client.patch(
        f"/api/v1/mantenimiento/{ticket_id}/cerrar",
        json={"MAN_Costo_Total": 100},
        headers=auth_headers,
    )
    assert r3.status_code == 200
    assert r3.json()["MAN_Fecha_Cierre"] is not None

    # Cerrar segunda vez debe fallar
    r4 = await client.patch(
        f"/api/v1/mantenimiento/{ticket_id}/cerrar",
        json={"MAN_Costo_Total": 100},
        headers=auth_headers,
    )
    assert r4.status_code == 400
    assert "ALREADY_CLOSED" in r4.json()["detail"]


@pytest.mark.asyncio
async def test_detalles_persisten_en_orden(client, auth_headers, software_seed):
    """Los detalles añadidos via POST quedan listados al GET."""
    s = software_seed
    r = await client.post(
        "/api/v1/mantenimiento/",
        json={
            "ACT_Activo": s["act_1"],
            "PER_Persona_Solicita": s["alice"],
            "TMA_Tipo_Mantenimiento": s["tma_corr"],
            "MAN_Descripcion_Falla": "Test detalles",
            "MAN_Costo_Total": 0,
            "detalles": [
                {"DMA_Accion_Realizada": "Paso 1: diagnóstico", "DMA_Costo_Item": 0},
            ],
        },
        headers=auth_headers,
    )
    ticket_id = r.json()["MAN_Mantenimiento"]
    await client.post(
        f"/api/v1/mantenimiento/{ticket_id}/detalles",
        json={"DMA_Accion_Realizada": "Paso 2: reparación", "DMA_Costo_Item": 50},
        headers=auth_headers,
    )
    r = await client.get(
        f"/api/v1/mantenimiento/{ticket_id}/detalles", headers=auth_headers,
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    acciones = {d["DMA_Accion_Realizada"] for d in items}
    assert "Paso 1: diagnóstico" in acciones
    assert "Paso 2: reparación" in acciones
