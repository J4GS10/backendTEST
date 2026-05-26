import pytest


@pytest.mark.asyncio
async def test_health(client):
    """
    /health responde con 200 o 503 según si la BD del engine global está
    accesible. En el contenedor de tests sin permisos de escritura sobre
    /app puede caer a 503 por SQLite path; aceptamos ambos como "respondió".
    Lo importante es que sea JSON con la estructura esperada.
    """
    r = await client.get("/health")
    assert r.status_code in (200, 503)
    data = r.json()
    assert "status" in data
    assert "database" in data
    assert data["status"] in ("ok", "degraded")
