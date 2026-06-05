"""Tests del módulo de Adjuntos por activo."""
import pytest


@pytest.mark.asyncio
async def test_upload_list_download_delete(client, auth_headers, domain_seed):
    act = domain_seed["act_1"]

    # 1. Subir
    up = await client.post(
        f"/api/v1/adjuntos/activos/{act}",
        headers=auth_headers,
        files={"file": ("factura.pdf", b"%PDF-1.4 contenido de prueba", "application/pdf")},
        data={"categoria": "factura", "descripcion": "Factura de compra"},
    )
    assert up.status_code == 201, up.text
    body = up.json()
    assert body["ADJ_Nombre_Original"] == "factura.pdf"
    assert body["ADJ_Categoria"] == "factura"
    assert body["ADJ_Tamano_Bytes"] > 0
    adj_id = body["ADJ_Adjunto"]

    # 2. Listar
    lst = await client.get(f"/api/v1/adjuntos/activos/{act}", headers=auth_headers)
    assert lst.status_code == 200
    assert len(lst.json()) == 1

    # 3. Descargar (contenido íntegro)
    dl = await client.get(f"/api/v1/adjuntos/{adj_id}/download", headers=auth_headers)
    assert dl.status_code == 200
    assert dl.content == b"%PDF-1.4 contenido de prueba"

    # 4. Borrar
    de = await client.delete(f"/api/v1/adjuntos/{adj_id}", headers=auth_headers)
    assert de.status_code == 204
    lst2 = await client.get(f"/api/v1/adjuntos/activos/{act}", headers=auth_headers)
    assert lst2.json() == []


@pytest.mark.asyncio
async def test_extension_no_permitida_400(client, auth_headers, domain_seed):
    act = domain_seed["act_1"]
    r = await client.post(
        f"/api/v1/adjuntos/activos/{act}",
        headers=auth_headers,
        files={"file": ("malware.exe", b"MZ...", "application/octet-stream")},
        data={"categoria": "otro"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "FILE_TYPE_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_categoria_invalida_400(client, auth_headers, domain_seed):
    act = domain_seed["act_1"]
    r = await client.post(
        f"/api/v1/adjuntos/activos/{act}",
        headers=auth_headers,
        files={"file": ("foto.png", b"\x89PNG\r\n", "image/png")},
        data={"categoria": "ilegal"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "INVALID_ATTACHMENT_CATEGORY"


@pytest.mark.asyncio
async def test_activo_inexistente_404(client, auth_headers, domain_seed):
    import uuid
    r = await client.post(
        f"/api/v1/adjuntos/activos/{uuid.uuid4()}",
        headers=auth_headers,
        files={"file": ("foto.png", b"\x89PNG\r\n", "image/png")},
        data={"categoria": "foto"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "ASSET_NOT_FOUND"


@pytest.mark.asyncio
async def test_upload_queda_auditado(client, auth_headers, domain_seed, session):
    from sqlalchemy import select
    from app.models.governance import AuditoriaSistema

    act = domain_seed["act_1"]
    await client.post(
        f"/api/v1/adjuntos/activos/{act}",
        headers=auth_headers,
        files={"file": ("acta.pdf", b"%PDF acta firmada", "application/pdf")},
        data={"categoria": "acta"},
    )
    ev = (await session.execute(
        select(AuditoriaSistema)
        .where(AuditoriaSistema.AUD_Accion == "CREATE",
               AuditoriaSistema.AUD_Entidad_Afectada == "INV_ADJUNTO")
        .order_by(AuditoriaSistema.AUD_Fecha_Hora.desc())
    )).scalars().first()
    assert ev is not None
    assert ev.AUD_Snapshot_JSON["categoria"] == "acta"
