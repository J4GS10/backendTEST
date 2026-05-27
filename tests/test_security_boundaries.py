"""
Tests de límites de seguridad: RBAC, validaciones, idempotencia.
"""
import pytest


@pytest.mark.asyncio
async def test_endpoints_sin_token_devuelven_401(client):
    """Sin Authorization header, los endpoints autenticados devuelven 401."""
    for ep in (
        "/api/v1/me",
        "/api/v1/core/activos",
        "/api/v1/org/personas",
        "/api/v1/cat/marcas",
    ):
        r = await client.get(ep)
        assert r.status_code == 401, f"{ep} debió devolver 401 sin token"


@pytest.mark.asyncio
async def test_q_filter_rechaza_strings_largos(client, auth_headers, domain_seed):
    """El filtro q tiene max_length=64 para frenar LIKE DoS."""
    payload = {"q": "a" * 100, "page": 1, "per_page": 5}
    r = await client.post(
        "/api/v1/core/activos/search", json=payload, headers=auth_headers,
    )
    assert r.status_code == 422
    detail = r.json()
    assert detail["detail"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_q_filter_escapa_wildcards_like(
    client, auth_headers, domain_seed,
):
    """
    Un q con `%` no debe devolver 'todos los activos': el escape debe
    convertirlo en literal. Para LAP-001 / LAP-002, buscar `%` no debe matchear.
    """
    r = await client.post(
        "/api/v1/core/activos/search",
        json={"q": "%", "page": 1, "per_page": 50},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0, (
        f"q='%' debió ser tratado como literal y no matchear; "
        f"total={body['total']} indica que el escape NO funcionó"
    )


@pytest.mark.asyncio
async def test_idempotency_key_regex_obligatoria(client, auth_headers, domain_seed):
    """Si llega Idempotency-Key, debe cumplir ^[A-Za-z0-9_-]{16,128}$."""
    headers = {**auth_headers, "Idempotency-Key": "!!too$short!!"}
    r = await client.post(
        "/api/v1/cat/marcas",
        json={"MAR_Nombre": "X"},
        headers=headers,
    )
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_paginacion_envoltorio_completo(client, auth_headers, domain_seed):
    """`/core/activos/search` devuelve {items, total, page, per_page}."""
    r = await client.post(
        "/api/v1/core/activos/search",
        json={"page": 1, "per_page": 10},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    for key in ("items", "total", "page", "per_page"):
        assert key in body
    assert body["total"] == 2  # LAP-001 + LAP-002 del domain_seed
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_modelos_flat_incluye_marca_embebida(client, auth_headers, domain_seed):
    """El endpoint flat devuelve modelo + marca en una sola fila."""
    r = await client.get("/api/v1/cat/modelos-flat", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 1
    for item in items:
        assert "MAR_Nombre" in item, "Cada modelo plano debe traer MAR_Nombre"
        assert "MOD_Nombre" in item


@pytest.mark.asyncio
async def test_gov_config_no_requiere_auth(client, domain_seed):
    """
    `/gov/config` es accesible sin login (para la pantalla de login que
    muestra logo/colores). Pero NO debe exponer secretos.
    """
    r = await client.get("/api/v1/gov/config")
    assert r.status_code == 200
    body = r.json()
    # No debe exponer SECRET_KEY ni FIELD_ENCRYPTION_KEY
    body_str = str(body).lower()
    assert "secret_key" not in body_str
    assert "encryption" not in body_str
    assert "password" not in body_str
