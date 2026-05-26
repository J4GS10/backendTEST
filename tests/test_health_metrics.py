"""Tests de health checks y métricas.

Nota: /health/full y /metrics usan el `engine` global (no el override de get_db),
así que en pytest la DB sqlite del engine global puede no ser accesible.
Verificamos formato y que la app responde sin crash; aceptamos 200 o 503.
"""
import pytest


@pytest.mark.asyncio
async def test_health_full_reachable(client, sa_user):
    """/health/full devuelve JSON estructurado independientemente del estado."""
    r = await client.get("/health/full")
    assert r.status_code in (200, 503)
    body = r.json()
    assert "status" in body
    assert "components" in body
    assert "database" in body["components"]
    assert "redis" in body["components"]
    assert "version" in body


@pytest.mark.asyncio
async def test_metrics_reachable(client, sa_user):
    """/metrics responde texto plano o 503 si el engine global no es accesible."""
    r = await client.get("/metrics")
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        body = r.text
        assert "inv_activos_total" in body
        assert "inv_usuarios_activos" in body
        assert "inv_tokens_revocados" in body
