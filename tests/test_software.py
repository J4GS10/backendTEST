"""
Tests del flujo software/licencias/instalaciones.

Garantías:
  - Instalar licencia incrementa LIC_Cantidad_Usada.
  - Desinstalar decrementa LIC_Cantidad_Usada.
  - Idempotency-Key permite reintentos sin duplicar la instalación.
  - No se puede instalar si LIC_Cantidad_Usada >= LIC_Cantidad_Total.
  - No se puede instalar 2 veces la misma licencia en el mismo activo.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.software import Licencia, Instalacion


def _u(v):
    return uuid.UUID(v) if isinstance(v, str) else v


@pytest.mark.asyncio
async def test_instalar_licencia_incrementa_uso(client, auth_headers, software_seed, session):
    s = software_seed
    r = await client.post(
        "/api/v1/soft/instalaciones",
        json={
            "ACT_Activo": s["act_1"],
            "LIC_Licencia": s["lic"],
            "INS_Fecha_Instalacion": "2026-05-28",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    session.expire_all()
    lic = (await session.execute(
        select(Licencia).where(Licencia.LIC_Licencia == s["lic"])
    )).scalar_one()
    assert lic.LIC_Cantidad_Usada == 1


@pytest.mark.asyncio
async def test_desinstalar_decrementa_uso(client, auth_headers, software_seed, session):
    s = software_seed
    payload = {
        "ACT_Activo": s["act_1"],
        "LIC_Licencia": s["lic"],
        "INS_Fecha_Instalacion": "2026-05-28",
    }
    await client.post("/api/v1/soft/instalaciones", json=payload, headers=auth_headers)
    r = await client.post(
        "/api/v1/soft/instalaciones/desinstalar", json=payload, headers=auth_headers,
    )
    assert r.status_code == 200
    session.expire_all()
    lic = (await session.execute(
        select(Licencia).where(Licencia.LIC_Licencia == s["lic"])
    )).scalar_one()
    assert lic.LIC_Cantidad_Usada == 0


@pytest.mark.asyncio
async def test_idempotency_key_no_duplica_instalacion(
    client, auth_headers, software_seed, session,
):
    """Re-enviar el mismo POST con la misma Idempotency-Key NO debe crear 2 filas."""
    s = software_seed
    key = "abcdef1234567890ABCDEF"  # cumple regex ^[A-Za-z0-9_-]{16,128}$
    payload = {
        "ACT_Activo": s["act_1"],
        "LIC_Licencia": s["lic"],
        "INS_Fecha_Instalacion": "2026-05-28",
    }
    h = {**auth_headers, "Idempotency-Key": key}
    r1 = await client.post("/api/v1/soft/instalaciones", json=payload, headers=h)
    r2 = await client.post("/api/v1/soft/instalaciones", json=payload, headers=h)
    assert r1.status_code == 201
    # Segundo request retorna 201 (cached) con el mismo INS_Instalacion.
    assert r2.status_code == 201
    assert r1.json()["INS_Instalacion"] == r2.json()["INS_Instalacion"]

    session.expire_all()
    rows = (await session.execute(
        select(Instalacion).where(
            Instalacion.ACT_Activo == _u(s["act_1"]),
            Instalacion.LIC_Licencia == s["lic"],
        )
    )).scalars().all()
    # Una sola fila de instalación.
    assert len([r for r in rows if r.INS_Estado]) == 1


@pytest.mark.asyncio
async def test_no_se_puede_exceder_cantidad_total_licencia(
    client, auth_headers, software_seed, session,
):
    """La licencia tiene LIC_Cantidad_Total=5. Pre-llenar a 5 y verificar
    que la siguiente instalación falla."""
    from sqlalchemy import update
    s = software_seed
    await session.execute(
        update(Licencia)
        .where(Licencia.LIC_Licencia == s["lic"])
        .values(LIC_Cantidad_Usada=5)
    )
    await session.commit()

    r = await client.post(
        "/api/v1/soft/instalaciones",
        json={
            "ACT_Activo": s["act_1"],
            "LIC_Licencia": s["lic"],
            "INS_Fecha_Instalacion": "2026-05-28",
        },
        headers=auth_headers,
    )
    assert r.status_code in (400, 409)
    detail = r.json()["detail"]
    assert "LICEN" in detail.upper() or "SOLD_OUT" in detail.upper() or "FULL" in detail.upper()


@pytest.mark.asyncio
async def test_no_duplicar_licencia_en_mismo_activo(
    client, auth_headers, software_seed,
):
    """Instalar la misma LIC en el mismo activo dos veces debe fallar."""
    s = software_seed
    payload = {
        "ACT_Activo": s["act_1"],
        "LIC_Licencia": s["lic"],
        "INS_Fecha_Instalacion": "2026-05-28",
    }
    r1 = await client.post("/api/v1/soft/instalaciones", json=payload, headers=auth_headers)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/soft/instalaciones", json=payload, headers=auth_headers)
    # Sin Idempotency-Key, el segundo intento debería fallar por duplicado activo.
    assert r2.status_code in (400, 409)
