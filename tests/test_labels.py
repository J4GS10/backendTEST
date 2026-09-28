"""Tests de etiquetas QR y resolucion por codigo escaneado."""
import pytest


@pytest.mark.asyncio
async def test_get_activo_by_codigo_para_scanner(client, auth_headers, domain_seed):
    d = domain_seed
    r = await client.get("/api/v1/core/activos/by-code/LAP-001", headers=auth_headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ACT_Activo"] == d["act_1"]
    assert body["ACT_Codigo_Interno"] == "LAP-001"


@pytest.mark.asyncio
async def test_generar_etiquetas_pdf(client, auth_headers, domain_seed):
    d = domain_seed
    r = await client.post(
        "/api/v1/core/activos/etiquetas.pdf",
        json={"activos_ids": [d["act_1"], d["act_2"]]},
        headers=auth_headers,
    )

    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF")
