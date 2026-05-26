"""Tests de paginación server-side en /core/activos/search."""
import pytest


@pytest.mark.asyncio
async def test_search_activos_returns_paginated_envelope(client, auth_headers):
    """POST /core/activos/search devuelve {items, total, page, per_page} aunque esté vacío."""
    r = await client.post(
        "/api/v1/core/activos/search",
        json={"page": 1, "per_page": 25},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "per_page" in body
    assert body["page"] == 1
    assert body["per_page"] == 25
    assert isinstance(body["items"], list)
    assert isinstance(body["total"], int)


@pytest.mark.asyncio
async def test_search_activos_validates_filters(client, auth_headers):
    """page debe ser >= 1, per_page debe respetar máximo."""
    r = await client.post(
        "/api/v1/core/activos/search",
        json={"page": 0, "per_page": 25},
        headers=auth_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_modelos_flat_endpoint(client, auth_headers):
    """/cat/modelos-flat devuelve la marca embebida (campo MAR_Nombre)."""
    r = await client.get("/api/v1/cat/modelos-flat", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list)
    # Si hay items, todos deben llevar MAR_Nombre + MOD_Nombre.
    for item in data:
        assert "MOD_Modelo" in item
        assert "MOD_Nombre" in item
        assert "MAR_Marca" in item
        assert "MAR_Nombre" in item
