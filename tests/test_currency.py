"""Moneda por registro: cada monto conserva la moneda en que se pagó.

  - Un activo se registra en GTQ, USD o CHF y la conserva al editarlo.
  - Una moneda no admitida se rechaza.
  - Los activos recibidos de una orden toman la moneda de la orden.
  - El mantenimiento conserva su moneda al cerrarse (o la cambia si se indica).
  - El tablero da un total por moneda; nunca suma quetzales con dólares.
"""
import pytest


def _activo(seed, serie, codigo, **extra):
    return {
        "ACT_Serie_Fabricante": serie, "ACT_Codigo_Interno": codigo,
        "ACT_Fecha_Compra": "2026-01-10", "MOD_Modelo": seed["mod"],
        "TAC_Tipo_Activo": seed["tac_lap"], "EOP_Estado_Operativo": seed["eop_disp"],
        "SED_Sede": seed["sede"], **extra,
    }


@pytest.mark.asyncio
async def test_activo_conserva_su_moneda(client, auth_headers, domain_seed):
    h = auth_headers
    r = await client.post("/api/v1/core/activos", headers=h, json=_activo(
        domain_seed, "CUR-USD-1", "LAP-USD-1", ACT_Costo="850.00", ACT_Moneda="usd"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ACT_Moneda"] == "USD"
    assert float(body["ACT_Costo"]) == 850.0

    # Sin indicarla, la moneda es GTQ.
    r = await client.post("/api/v1/core/activos", headers=h, json=_activo(
        domain_seed, "CUR-GTQ-1", "LAP-GTQ-1", ACT_Costo="6500.00"))
    assert r.status_code == 201, r.text
    assert r.json()["ACT_Moneda"] == "GTQ"

    # Editar solo el costo no cambia la moneda.
    aid = body["ACT_Activo"]
    r = await client.patch(f"/api/v1/core/activos/{aid}", headers=h, json={"ACT_Costo": "900.00"})
    assert r.status_code == 200, r.text
    assert r.json()["ACT_Moneda"] == "USD"

    r = await client.patch(f"/api/v1/core/activos/{aid}", headers=h, json={"ACT_Moneda": "GTQ"})
    assert r.status_code == 200, r.text
    assert r.json()["ACT_Moneda"] == "GTQ"


@pytest.mark.asyncio
async def test_moneda_no_admitida_se_rechaza(client, auth_headers, domain_seed):
    r = await client.post("/api/v1/core/activos", headers=auth_headers, json=_activo(
        domain_seed, "CUR-EUR-1", "LAP-EUR-1", ACT_Costo="100", ACT_Moneda="EUR"))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_recepcion_en_dolares_crea_activo_en_dolares(client, auth_headers, domain_seed):
    h = auth_headers
    pid = (await client.post("/api/v1/compras/proveedores", headers=h,
           json={"PRV_Nombre": "Proveedor USD"})).json()["PRV_Proveedor"]
    orden = (await client.post("/api/v1/compras/ordenes", headers=h, json={
        "OCO_Numero": "OC-USD-1", "OCO_Fecha": "2026-06-01", "PRV_Proveedor": pid,
        "OCO_Moneda": "USD", "SED_Sede": domain_seed["sede"],
        "lineas": [{"OCL_Descripcion": "Laptop", "OCL_Cantidad": 1, "OCL_Precio_Unitario": "1200"}],
    })).json()
    linea = orden["lineas"][0]["OCL_Linea"]

    r = await client.post(f"/api/v1/compras/ordenes/{orden['OCO_Orden']}/recibir", headers=h, json={
        "activos": [{
            "OCL_Linea": linea, "ACT_Serie_Fabricante": "CUR-REC-USD",
            "MOD_Modelo": domain_seed["mod"], "TAC_Tipo_Activo": domain_seed["tac_lap"],
            "ACT_Fecha_Compra": "2026-06-01",
        }],
    })
    assert r.status_code == 200, r.text
    codigo = r.json()["activos_codigos"][0]

    r = await client.get(f"/api/v1/core/activos/by-code/{codigo}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["ACT_Moneda"] == "USD"
    assert float(r.json()["ACT_Costo"]) == 1200.0


@pytest.mark.asyncio
async def test_mantenimiento_conserva_su_moneda(client, auth_headers, software_seed):
    s = software_seed
    r = await client.post("/api/v1/mantenimiento/", headers=auth_headers, json={
        "ACT_Activo": s["act_1"], "PER_Persona_Solicita": s["alice"],
        "TMA_Tipo_Mantenimiento": s["tma_corr"], "MAN_Descripcion_Falla": "Pantalla",
        "MAN_Costo_Total": 0, "MAN_Moneda": "USD",
    })
    assert r.status_code == 201, r.text
    assert r.json()["MAN_Moneda"] == "USD"
    tid = r.json()["MAN_Mantenimiento"]

    r = await client.patch(f"/api/v1/mantenimiento/{tid}/cerrar", headers=auth_headers,
                           json={"MAN_Costo_Total": 150})
    assert r.status_code == 200, r.text
    assert r.json()["MAN_Moneda"] == "USD"


@pytest.mark.asyncio
async def test_tablero_totaliza_por_moneda(client, auth_headers, domain_seed):
    h = auth_headers
    for serie, codigo, costo, moneda in (
        ("CUR-T-1", "LAP-T-1", "100.00", "GTQ"),
        ("CUR-T-2", "LAP-T-2", "250.00", "GTQ"),
        ("CUR-T-3", "LAP-T-3", "80.00", "USD"),
    ):
        r = await client.post("/api/v1/core/activos", headers=h, json=_activo(
            domain_seed, serie, codigo, ACT_Costo=costo, ACT_Moneda=moneda))
        assert r.status_code == 201, r.text

    stats = (await client.get("/api/v1/stats/dashboard", headers=h)).json()
    por_moneda = stats["costo_inventario_por_moneda"]
    assert por_moneda["USD"] == 80.0
    assert por_moneda["GTQ"] >= 350.0  # más lo que traiga el seed
    assert "costo_inventario" not in stats  # ya no existe un total mezclado
