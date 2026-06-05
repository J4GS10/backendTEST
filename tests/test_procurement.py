"""Tests del módulo de Compras (Proveedores, Órdenes, Garantías)."""
import uuid
from datetime import date, timedelta

import pytest


async def _crear_proveedor(client, headers, nombre="Distribuidora TI"):
    return await client.post("/api/v1/compras/proveedores", headers=headers, json={
        "PRV_Nombre": nombre,
        "PRV_Identificacion_Fiscal": "NIT-12345",
        "PRV_Email": "ventas@distri.example.com",
    })


@pytest.mark.asyncio
async def test_proveedor_crud_y_duplicado(client, auth_headers, sa_user):
    r = await _crear_proveedor(client, auth_headers)
    assert r.status_code == 201, r.text
    pid = r.json()["PRV_Proveedor"]

    dup = await _crear_proveedor(client, auth_headers)
    assert dup.status_code == 409
    assert dup.json()["detail"] == "SUPPLIER_ALREADY_EXISTS"

    upd = await client.patch(f"/api/v1/compras/proveedores/{pid}", headers=auth_headers,
                             json={"PRV_Telefono": "555-1234"})
    assert upd.status_code == 200
    assert upd.json()["PRV_Telefono"] == "555-1234"

    lst = await client.get("/api/v1/compras/proveedores", headers=auth_headers)
    assert len(lst.json()) == 1


@pytest.mark.asyncio
async def test_crear_orden_calcula_total(client, auth_headers, sa_user):
    pid = (await _crear_proveedor(client, auth_headers)).json()["PRV_Proveedor"]
    r = await client.post("/api/v1/compras/ordenes", headers=auth_headers, json={
        "OCO_Numero": "OC-2026-001",
        "OCO_Fecha": "2026-06-01",
        "OCO_Moneda": "USD",
        "PRV_Proveedor": pid,
        "lineas": [
            {"OCL_Descripcion": "Laptop Dell", "OCL_Cantidad": 2, "OCL_Precio_Unitario": "850.50"},
            {"OCL_Descripcion": "Mouse", "OCL_Cantidad": 5, "OCL_Precio_Unitario": "10.00"},
        ],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    # 2*850.50 + 5*10 = 1701.00 + 50.00 = 1751.00
    assert float(body["OCO_Total"]) == 1751.00
    assert len(body["lineas"]) == 2
    assert body["OCO_Estado"] == "BORRADOR"
    assert body["proveedor"]["PRV_Nombre"] == "Distribuidora TI"


@pytest.mark.asyncio
async def test_numero_orden_duplicado_409(client, auth_headers, sa_user):
    pid = (await _crear_proveedor(client, auth_headers)).json()["PRV_Proveedor"]
    payload = {"OCO_Numero": "OC-DUP", "OCO_Fecha": "2026-06-01", "PRV_Proveedor": pid, "lineas": []}
    a = await client.post("/api/v1/compras/ordenes", headers=auth_headers, json=payload)
    assert a.status_code == 201
    b = await client.post("/api/v1/compras/ordenes", headers=auth_headers, json=payload)
    assert b.status_code == 409
    assert b.json()["detail"] == "PURCHASE_ORDER_NUMBER_EXISTS"


@pytest.mark.asyncio
async def test_cambiar_estado_orden(client, auth_headers, sa_user):
    pid = (await _crear_proveedor(client, auth_headers)).json()["PRV_Proveedor"]
    oid = (await client.post("/api/v1/compras/ordenes", headers=auth_headers, json={
        "OCO_Numero": "OC-EST", "OCO_Fecha": "2026-06-01", "PRV_Proveedor": pid, "lineas": []})).json()["OCO_Orden"]

    r = await client.patch(f"/api/v1/compras/ordenes/{oid}/estado", headers=auth_headers,
                           json={"OCO_Estado": "RECIBIDA"})
    assert r.status_code == 200
    assert r.json()["OCO_Estado"] == "RECIBIDA"


@pytest.mark.asyncio
async def test_no_borrar_proveedor_con_ordenes(client, auth_headers, sa_user):
    pid = (await _crear_proveedor(client, auth_headers)).json()["PRV_Proveedor"]
    await client.post("/api/v1/compras/ordenes", headers=auth_headers, json={
        "OCO_Numero": "OC-X", "OCO_Fecha": "2026-06-01", "PRV_Proveedor": pid, "lineas": []})
    r = await client.delete(f"/api/v1/compras/proveedores/{pid}", headers=auth_headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "CANNOT_DELETE_SUPPLIER_HAS_ORDERS"


@pytest.mark.asyncio
async def test_garantias_deriva_proveedor_y_estado(client, auth_headers, domain_seed, session):
    from sqlalchemy import select
    from app.models.core import Activo

    # Poner una garantía próxima a vencer al activo act_1.
    act_id = domain_seed["act_1"]
    act = (await session.execute(
        select(Activo).where(Activo.ACT_Activo == uuid.UUID(act_id)))).scalar_one()
    act.ACT_Fin_Garantia = date.today() + timedelta(days=30)
    await session.commit()

    pid = (await _crear_proveedor(client, auth_headers)).json()["PRV_Proveedor"]
    # Orden con una línea que enlaza al activo.
    await client.post("/api/v1/compras/ordenes", headers=auth_headers, json={
        "OCO_Numero": "OC-GAR", "OCO_Fecha": "2026-01-01", "PRV_Proveedor": pid,
        "lineas": [{"OCL_Descripcion": "Laptop", "OCL_Cantidad": 1, "OCL_Precio_Unitario": "1000",
                    "ACT_Activo": act_id}]})

    g = await client.get("/api/v1/compras/garantias?dias=90&solo_alertas=true", headers=auth_headers)
    assert g.status_code == 200, g.text
    fila = next((x for x in g.json() if x["ACT_Activo"] == act_id), None)
    assert fila is not None
    assert fila["estado_garantia"] == "por_vencer"
    assert fila["proveedor"] == "Distribuidora TI"
    assert fila["dias_restantes"] == 30
