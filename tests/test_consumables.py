"""Tests del módulo de Consumibles (inventario por cantidad)."""
import pytest


async def _crear(client, headers, **over):
    payload = {
        "CON_Nombre": over.get("nombre", "Toner HP 26A"),
        "CON_Unidad": "unidad",
        "CON_Stock_Actual": over.get("stock", 10),
        "CON_Stock_Minimo": over.get("minimo", 3),
    }
    return await client.post("/api/v1/consumibles", headers=headers, json=payload)


@pytest.mark.asyncio
async def test_crear_y_listar_consumible(client, auth_headers, sa_user):
    r = await _crear(client, auth_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["CON_Stock_Actual"] == 10
    assert body["bajo_stock"] is False

    lst = await client.get("/api/v1/consumibles", headers=auth_headers)
    assert lst.status_code == 200
    assert len(lst.json()) == 1


@pytest.mark.asyncio
async def test_nombre_duplicado_409(client, auth_headers, sa_user):
    await _crear(client, auth_headers)
    r = await _crear(client, auth_headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "CONSUMABLE_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_entrada_suma_y_salida_resta_stock(client, auth_headers, sa_user):
    cid = (await _crear(client, auth_headers, stock=5)).json()["CON_Consumible"]

    e = await client.post(f"/api/v1/consumibles/{cid}/entrada", headers=auth_headers,
                          json={"MOC_Cantidad": 7, "MOC_Motivo": "compra"})
    assert e.status_code == 201, e.text
    assert e.json()["MOC_Stock_Resultante"] == 12

    s = await client.post(f"/api/v1/consumibles/{cid}/salida", headers=auth_headers,
                          json={"MOC_Cantidad": 4, "MOC_Motivo": "entrega"})
    assert s.status_code == 201, s.text
    assert s.json()["MOC_Stock_Resultante"] == 8

    detalle = await client.get(f"/api/v1/consumibles/{cid}", headers=auth_headers)
    assert detalle.json()["CON_Stock_Actual"] == 8


@pytest.mark.asyncio
async def test_salida_sin_stock_suficiente_409(client, auth_headers, sa_user):
    cid = (await _crear(client, auth_headers, stock=2)).json()["CON_Consumible"]
    r = await client.post(f"/api/v1/consumibles/{cid}/salida", headers=auth_headers,
                          json={"MOC_Cantidad": 5})
    assert r.status_code == 409
    assert r.json()["detail"] == "INSUFFICIENT_STOCK"
    # El stock no cambió.
    detalle = await client.get(f"/api/v1/consumibles/{cid}", headers=auth_headers)
    assert detalle.json()["CON_Stock_Actual"] == 2


@pytest.mark.asyncio
async def test_bajo_stock_flag_y_filtro(client, auth_headers, sa_user):
    bajo = (await _crear(client, auth_headers, nombre="Cable HDMI", stock=2, minimo=5)).json()
    assert bajo["bajo_stock"] is True
    await _crear(client, auth_headers, nombre="Mouse USB", stock=20, minimo=5)

    solo_bajo = await client.get("/api/v1/consumibles?bajo_stock=true", headers=auth_headers)
    nombres = [c["CON_Nombre"] for c in solo_bajo.json()]
    assert nombres == ["Cable HDMI"]


@pytest.mark.asyncio
async def test_delete_con_movimientos_409(client, auth_headers, sa_user):
    cid = (await _crear(client, auth_headers)).json()["CON_Consumible"]
    await client.post(f"/api/v1/consumibles/{cid}/salida", headers=auth_headers,
                      json={"MOC_Cantidad": 1})
    r = await client.delete(f"/api/v1/consumibles/{cid}", headers=auth_headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "CANNOT_DELETE_CONSUMABLE_HAS_MOVEMENTS"


@pytest.mark.asyncio
async def test_movimiento_queda_auditado(client, auth_headers, sa_user, session):
    from sqlalchemy import select
    from app.models.governance import AuditoriaSistema

    cid = (await _crear(client, auth_headers)).json()["CON_Consumible"]
    await client.post(f"/api/v1/consumibles/{cid}/salida", headers=auth_headers,
                      json={"MOC_Cantidad": 2, "MOC_Motivo": "entrega a Juan"})

    ev = (await session.execute(
        select(AuditoriaSistema)
        .where(AuditoriaSistema.AUD_Accion == "STOCK_OUT",
               AuditoriaSistema.AUD_Entidad_Afectada == "INV_CONSUMIBLE")
        .order_by(AuditoriaSistema.AUD_Fecha_Hora.desc())
    )).scalars().first()
    assert ev is not None
    assert ev.AUD_Snapshot_JSON["cantidad"] == 2
    assert ev.AUD_Snapshot_JSON["stock_resultante"] == 8
