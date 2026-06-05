"""Tests de adjuntos en órdenes de compra (factura) y exports CSV nuevos."""
import pytest


async def _orden(client, h):
    pid = (await client.post("/api/v1/compras/proveedores", headers=h,
           json={"PRV_Nombre": "Prov Factura"})).json()["PRV_Proveedor"]
    return (await client.post("/api/v1/compras/ordenes", headers=h, json={
        "OCO_Numero": "OC-FAC-1", "OCO_Fecha": "2026-06-01", "PRV_Proveedor": pid,
        "lineas": []})).json()["OCO_Orden"]


@pytest.mark.asyncio
async def test_factura_en_orden(client, auth_headers, sa_user):
    oid = await _orden(client, auth_headers)
    up = await client.post(
        f"/api/v1/adjuntos/ordenes/{oid}",
        headers=auth_headers,
        files={"file": ("factura.pdf", b"%PDF factura orden", "application/pdf")},
        data={"categoria": "factura"},
    )
    assert up.status_code == 201, up.text
    body = up.json()
    assert body["OCO_Orden"] == oid
    assert body["ACT_Activo"] is None  # XOR: pertenece a la orden, no a un activo

    lst = await client.get(f"/api/v1/adjuntos/ordenes/{oid}", headers=auth_headers)
    assert len(lst.json()) == 1

    dl = await client.get(f"/api/v1/adjuntos/{body['ADJ_Adjunto']}/download", headers=auth_headers)
    assert dl.status_code == 200
    assert dl.content == b"%PDF factura orden"


@pytest.mark.asyncio
async def test_orden_inexistente_404(client, auth_headers, sa_user):
    r = await client.post(
        "/api/v1/adjuntos/ordenes/999999",
        headers=auth_headers,
        files={"file": ("f.pdf", b"x", "application/pdf")},
        data={"categoria": "factura"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "PURCHASE_ORDER_NOT_FOUND"


@pytest.mark.asyncio
async def test_exports_csv_nuevos(client, auth_headers, sa_user):
    # Crear algo de data
    await client.post("/api/v1/consumibles", headers=auth_headers, json={
        "CON_Nombre": "Cable export", "CON_Unidad": "u", "CON_Stock_Actual": 2, "CON_Stock_Minimo": 5})
    await client.post("/api/v1/compras/proveedores", headers=auth_headers, json={"PRV_Nombre": "Prov export"})

    for path, prefix in [("consumibles.csv", "Nombre"), ("proveedores.csv", "Nombre"), ("ordenes.csv", "Numero")]:
        r = await client.get(f"/api/v1/export/{path}", headers=auth_headers)
        assert r.status_code == 200, f"{path}: {r.text}"
        assert "text/csv" in r.headers["content-type"]
        # BOM UTF-8 + cabecera presente
        assert prefix in r.text
