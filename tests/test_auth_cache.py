"""Tests del decodificador de tokens + revocación."""
import pytest


@pytest.mark.asyncio
async def test_logout_revokes_token(client, auth_token, auth_headers):
    """Tras logout, el access_token deja de funcionar."""
    # /me debería funcionar antes de logout
    r1 = await client.get("/api/v1/me", headers=auth_headers)
    assert r1.status_code == 200

    # Logout
    r2 = await client.post("/api/v1/login/logout", headers=auth_headers)
    assert r2.status_code == 204

    # Mismo token ya no debe funcionar
    r3 = await client.get("/api/v1/me", headers=auth_headers)
    assert r3.status_code == 401
    assert r3.json()["detail"] == "TOKEN_REVOKED"


@pytest.mark.asyncio
async def test_password_change_invalidates_old_tokens(client, auth_token, auth_headers):
    """Cambiar contraseña revoca TODOS los tokens previos."""
    # Cambiar password
    r1 = await client.post(
        "/api/v1/me/password",
        json={"current_password": "TestPassw0rd!", "new_password": "NewPassw0rd!2026"},
        headers=auth_headers,
    )
    assert r1.status_code == 204, r1.text

    # Token viejo debe fallar
    r2 = await client.get("/api/v1/me", headers=auth_headers)
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_password_change_requires_current_password(client, auth_headers):
    """No se acepta cambio sin re-validar contraseña actual."""
    r = await client.post(
        "/api/v1/me/password",
        json={"current_password": "WRONG_PWD!1", "new_password": "NewPassw0rd!2026"},
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "INCORRECT_CURRENT_PASSWORD"
