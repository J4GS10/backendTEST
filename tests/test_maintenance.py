"""
Tests del flujo de mantenimiento.

Garantías:
  - Crear ticket lo deja abierto.
  - 1 solo ticket abierto por activo (constraint XOR).
  - Agregar detalle al ticket abierto funciona.
  - Cerrar el ticket marca MAN_Fecha_Cierre.
  - Cerrar 2 veces no es permitido.
  - Cerrar mantenimiento de un activo asignado deja el activo en 'Asignado'
    (no en 'Disponible' como hacía el bug previo al fix).
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.core import Activo


def _u(v):
    return uuid.UUID(v) if isinstance(v, str) else v


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
async def test_cerrar_mantenimiento_de_activo_asignado_lo_deja_asignado(
    client, auth_headers, software_seed, session,
):
    """
    BUG cerrado en 2026-05-28: al cerrar mantenimiento, el código forzaba
    estado='Disponible' sin verificar si había movimiento abierto. Si Pedro
    tenía el activo, tras el cierre quedaba 'Disponible' pero seguía siendo
    "dueño" en INV_MOVIMIENTO → INCONSISTENCIA.

    Comportamiento esperado: si hay movimiento abierto → 'Asignado';
    si no → 'En Bodega'.
    """
    s = software_seed
    # 1. Asignar act_1 a Alice
    await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": s["act_1"], "PER_Persona": s["alice"],
            "ARE_Area": s["area"], "TMO_Tipo_Movimiento": s["tmo_asg"],
        },
        headers=auth_headers,
    )
    # 2. Abrir mantenimiento → estado 'En Reparación'
    tr = await client.post(
        "/api/v1/mantenimiento/",
        json={
            "ACT_Activo": s["act_1"],
            "PER_Persona_Solicita": s["alice"],
            "TMA_Tipo_Mantenimiento": s["tma_corr"],
            "MAN_Descripcion_Falla": "Test bug cierre",
            "MAN_Costo_Total": 0,
        },
        headers=auth_headers,
    )
    ticket_id = tr.json()["MAN_Mantenimiento"]
    # 3. Cerrar mantenimiento
    await client.patch(
        f"/api/v1/mantenimiento/{ticket_id}/cerrar",
        json={"MAN_Costo_Total": 0},
        headers=auth_headers,
    )
    # 4. El activo debe estar 'Asignado' (no 'Disponible'), porque sigue
    # teniendo a Alice como custodia.
    session.expire_all()
    estado = (await session.execute(
        select(Activo.EOP_Estado_Operativo).where(Activo.ACT_Activo == _u(s["act_1"]))
    )).scalar()
    assert estado == s["eop_asig"], (
        f"BUG: tras cerrar mantenimiento, activo con movimiento abierto "
        f"debe quedar 'Asignado' (id={s['eop_asig']}), pero está en id={estado}"
    )


@pytest.mark.asyncio
async def test_cerrar_mantenimiento_sin_asignacion_va_a_bodega(
    client, auth_headers, software_seed, session,
):
    """Si no hay movimiento abierto, al cerrar mantenimiento → 'En Bodega'."""
    s = software_seed
    # act_2 ya está en Bodega y sin asignación
    tr = await client.post(
        "/api/v1/mantenimiento/",
        json={
            "ACT_Activo": s["act_2"],
            "PER_Persona_Solicita": s["alice"],
            "TMA_Tipo_Mantenimiento": s["tma_corr"],
            "MAN_Descripcion_Falla": "Test cierre sin asignación",
            "MAN_Costo_Total": 0,
        },
        headers=auth_headers,
    )
    ticket_id = tr.json()["MAN_Mantenimiento"]
    await client.patch(
        f"/api/v1/mantenimiento/{ticket_id}/cerrar",
        json={"MAN_Costo_Total": 0},
        headers=auth_headers,
    )
    session.expire_all()
    estado = (await session.execute(
        select(Activo.EOP_Estado_Operativo).where(Activo.ACT_Activo == _u(s["act_2"]))
    )).scalar()
    assert estado == s["eop_bod"], (
        f"Activo sin asignación tras cierre mant debe ir a 'En Bodega' "
        f"(id={s['eop_bod']}), pero está en id={estado}"
    )


@pytest.mark.asyncio
async def test_no_se_puede_dar_baja_activo_asignado(
    client, auth_headers, software_seed,
):
    """DELETE /core/activos/{id} debe fallar si el activo está asignado."""
    s = software_seed
    await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": s["act_1"], "PER_Persona": s["alice"],
            "ARE_Area": s["area"], "TMO_Tipo_Movimiento": s["tmo_asg"],
        },
        headers=auth_headers,
    )
    r = await client.delete(
        f"/api/v1/core/activos/{s['act_1']}", headers=auth_headers,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "CANNOT_DELETE_ASSIGNED_ASSET_RETURN_IT_FIRST"


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
