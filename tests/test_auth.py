"""Tests del flujo de autenticación, lockout y cambio de contraseña."""
import pytest


@pytest.mark.asyncio
async def test_login_ok(client, sa_user):
    r = await client.post(
        "/api/v1/login/access-token",
        data={"username": "sa", "password": "TestPassw0rd!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data and "refresh_token" in data


@pytest.mark.asyncio
async def test_login_bad_credentials_returns_400(client, sa_user):
    r = await client.post(
        "/api/v1/login/access-token",
        data={"username": "sa", "password": "wrong"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "INCORRECT_USERNAME_OR_PASSWORD"


@pytest.mark.asyncio
async def test_protected_endpoint_requires_token(client):
    r = await client.get("/api/v1/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_with_token(client, auth_headers):
    r = await client.get("/api/v1/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["username"] == "sa"
    assert r.json()["role"] == "SUPER_ADMIN"


@pytest.mark.asyncio
async def test_change_password_requires_current(client, auth_headers):
    r = await client.post(
        "/api/v1/me/password",
        json={"current_password": "wrong", "new_password": "NewPassw0rd!"},
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert "INCORRECT_CURRENT_PASSWORD" in r.json()["detail"]


@pytest.mark.asyncio
async def test_change_password_weak_rejected(client, auth_headers):
    r = await client.post(
        "/api/v1/me/password",
        json={"current_password": "TestPassw0rd!", "new_password": "weak"},
        headers=auth_headers,
    )
    # 400 por política o 422 por min_length=8 en Body
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_change_password_revokes_tokens(client, auth_headers, auth_token):
    # Cambia contraseña con éxito
    r = await client.post(
        "/api/v1/me/password",
        json={"current_password": "TestPassw0rd!", "new_password": "NewStr0ngPass!"},
        headers=auth_headers,
    )
    assert r.status_code == 204

    # El token anterior queda revocado (revocación global por usuario)
    r2 = await client.get("/api/v1/me", headers=auth_headers)
    assert r2.status_code == 401
