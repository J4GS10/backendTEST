"""Tests del modelo hibrido de autenticacion interna + SSO."""
import pytest


def test_sso_return_to_requires_exact_frontend_origin(monkeypatch):
    from app.core.config import settings
    from app.services.sso import SSOService

    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://localhost")
    default = "https://localhost/sso/callback"

    assert SSOService._safe_return_to("https://localhost/sso/callback?next=/") == (
        "https://localhost/sso/callback?next=/"
    )
    assert SSOService._safe_return_to("https://localhost.evil.example/capture") == default
    assert SSOService._safe_return_to("https://evil.example/") == default
    assert SSOService._safe_return_to("//evil.example/capture") == default


@pytest.mark.asyncio
async def test_crear_usuario_sso_sin_password_y_login_interno_falla(
    client, auth_headers, domain_seed,
):
    d = domain_seed
    r = await client.post(
        "/api/v1/org/usuarios",
        headers=auth_headers,
        json={
            "USU_Username": "sso_bob",
            "USU_Rol": "TECNICO", "USU_Alcance_Global": True,
            "PER_Persona": d["bob"],
            "USU_SSO_Habilitado": True,
            "USU_SSO_Provider": "microsoft",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["USU_SSO_Habilitado"] is True
    assert body["USU_SSO_Provider"] == "microsoft"

    login = await client.post(
        "/api/v1/login/access-token",
        data={"username": "sso_bob", "password": "NoPassword#2026"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login.status_code == 400
    assert login.json()["detail"] == "INCORRECT_USERNAME_OR_PASSWORD"


@pytest.mark.asyncio
async def test_crear_usuario_exige_password_o_sso(client, auth_headers, domain_seed):
    d = domain_seed
    r = await client.post(
        "/api/v1/org/usuarios",
        headers=auth_headers,
        json={
            "USU_Username": "sin_metodo",
            "USU_Rol": "TECNICO", "USU_Alcance_Global": True,
            "PER_Persona": d["bob"],
        },
    )
    assert r.status_code == 422
