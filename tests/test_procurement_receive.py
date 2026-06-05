"""Tests del lazo cerrado: recepción de orden (stock + alta de activos) y alertas."""
import pytest


async def _proveedor(client, h):
    return (await client.post("/api/v1/compras/proveedores", headers=h,
            json={"PRV_Nombre": "Distribuidora Recibe"})).json()["PRV_Proveedor"]


@pytest.mark.asyncio
async def test_recibir_orden_suma_stock_y_crea_activo(client, auth_headers, domain_seed):
    h = auth_headers
    pid = await _proveedor(client, h)

    # Consumible con stock inicial 5.
    cid = (await client.post("/api/v1/consumibles", headers=h, json={
        "CON_Nombre": "Toner recepción", "CON_Unidad": "unidad",
        "CON_Stock_Actual": 5, "CON_Stock_Minimo": 2})).json()["CON_Consumible"]

    # Orden con 2 líneas: una será consumible, otra activo.
    orden = (await client.post("/api/v1/compras/ordenes", headers=h, json={
        "OCO_Numero": "OC-REC-1", "OCO_Fecha": "2026-06-01", "PRV_Proveedor": pid,
        "lineas": [
            {"OCL_Descripcion": "Toner HP", "OCL_Cantidad": 10, "OCL_Precio_Unitario": "30"},
            {"OCL_Descripcion": "Laptop nueva", "OCL_Cantidad": 1, "OCL_Precio_Unitario": "1200"},
        ]})).json()
    oid = orden["OCO_Orden"]
    linea_con = next(l["OCL_Linea"] for l in orden["lineas"] if "Toner" in l["OCL_Descripcion"])
    linea_act = next(l["OCL_Linea"] for l in orden["lineas"] if "Laptop" in l["OCL_Descripcion"])

    # Recibir: reabastece el consumible (+10) y crea el activo.
    r = await client.post(f"/api/v1/compras/ordenes/{oid}/recibir", headers=h, json={
        "consumibles": [{"OCL_Linea": linea_con, "CON_Consumible": cid, "cantidad": 10}],
        "activos": [{
            "OCL_Linea": linea_act, "ACT_Serie_Fabricante": "REC-SER-001",
            "MOD_Modelo": domain_seed["mod"], "TAC_Tipo_Activo": domain_seed["tac_lap"],
            "ACT_Fecha_Compra": "2026-06-01", "ACT_Fin_Garantia": "2028-06-01",
        }],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["consumibles_reabastecidos"] == 1
    assert body["activos_creados"] == 1
    assert body["OCO_Estado"] == "RECIBIDA"
    codigo_nuevo = body["activos_codigos"][0]

    # Stock del consumible subió 5 -> 15.
    assert (await client.get(f"/api/v1/consumibles/{cid}", headers=h)).json()["CON_Stock_Actual"] == 15
    # La orden quedó RECIBIDA.
    assert (await client.get(f"/api/v1/compras/ordenes/{oid}", headers=h)).json()["OCO_Estado"] == "RECIBIDA"

    # El activo nuevo aparece en garantías CON su proveedor derivado de la orden.
    g = (await client.get("/api/v1/compras/garantias?dias=3650", headers=h)).json()
    fila = next((x for x in g if x["ACT_Codigo_Interno"] == codigo_nuevo), None)
    assert fila is not None
    assert fila["proveedor"] == "Distribuidora Recibe"


@pytest.mark.asyncio
async def test_recibir_dos_veces_409(client, auth_headers, domain_seed):
    h = auth_headers
    pid = await _proveedor(client, h)
    oid = (await client.post("/api/v1/compras/ordenes", headers=h, json={
        "OCO_Numero": "OC-REC-2", "OCO_Fecha": "2026-06-01", "PRV_Proveedor": pid,
        "lineas": []})).json()["OCO_Orden"]
    a = await client.post(f"/api/v1/compras/ordenes/{oid}/recibir", headers=h,
                          json={"consumibles": [], "activos": []})
    assert a.status_code == 200
    b = await client.post(f"/api/v1/compras/ordenes/{oid}/recibir", headers=h,
                          json={"consumibles": [], "activos": []})
    assert b.status_code == 409
    assert b.json()["detail"] == "ORDER_NOT_RECEIVABLE"


@pytest.mark.asyncio
async def test_notificar_garantias_devuelve_conteo(client, auth_headers, domain_seed, session):
    import uuid
    from datetime import date, timedelta
    from sqlalchemy import select
    from app.models.core import Activo
    act = (await session.execute(
        select(Activo).where(Activo.ACT_Activo == uuid.UUID(domain_seed["act_1"])))).scalar_one()
    act.ACT_Fin_Garantia = date.today() + timedelta(days=20)
    await session.commit()

    r = await client.post("/api/v1/compras/garantias/notificar?dias=90", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 1


def test_templates_alerta_renderizan():
    """Las plantillas nuevas renderizan subject+html sin error."""
    from app.core.email import send_notification_sync_for_tests
    s1, h1, _ = send_notification_sync_for_tests(
        "stock_bajo", {"codigo": "Toner", "stock_actual": 1, "stock_minimo": 5, "unidad": "u"})
    assert "Stock bajo" in s1 and "Toner" in h1
    s2, h2, _ = send_notification_sync_for_tests(
        "garantia_por_vencer",
        {"total": 2, "dias": 90, "items": [{"codigo": "LPT001", "fin": "2026-07-01", "estado": "Por vencer", "dias": 28}]})
    assert "Garant" in s2 and "LPT001" in h2
