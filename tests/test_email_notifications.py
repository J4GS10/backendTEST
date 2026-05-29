"""
Tests del servicio de notificaciones por email.

Los tests NO mandan emails reales: SMTP_HOST está vacío en conftest, por lo
que `send_notification` cae al modo silencioso (loguea pero no envía). En su
lugar usamos `send_notification_sync_for_tests` para verificar templates +
destinatarios + subject sin tocar SMTP.

También validamos que:
  - Las operaciones de negocio NO se rompen si SMTP falla.
  - El template renderiza variables esperadas (sin KeyError ni HTML mal formado).
"""
import os
import uuid

import pytest

from app.core.email import _SUBJECTS, _TEMPLATES, _render, send_notification_sync_for_tests


def _u(v):
    return uuid.UUID(v) if isinstance(v, str) else v


@pytest.mark.asyncio
async def test_templates_renderizan_sin_error():
    """Cada template definido renderiza con un contexto mínimo sin reventar."""
    base_ctx = {
        "codigo": "LAP-001", "serie": "SER-001", "tipo": "Laptop",
        "marca": "Acme", "modelo": "X1", "hostname": "host-1",
        "persona_nombre": "Alice Test", "persona_email": "alice@test.local",
        "fecha": "2026-05-29T12:00:00", "area": "TI", "observacion": "test",
        "origen_nombre": "Alice", "destino_nombre": "Bob",
        "motivo": "Obsolescencia", "num_activos": 2,
        "activos_lista": ["LAP-001", "MON-001"],
        "usuario_desactivado": "Sí", "descripcion": "No enciende",
        "costo": "0", "estado_final": "En Bodega",
    }
    for name in _TEMPLATES:
        subject, html = _render(name, base_ctx)
        assert subject, f"Template {name} produjo subject vacío"
        assert "<div" in html or "<table" in html, f"Template {name} HTML inválido"
        # Garantiza que NO queda variable Jinja sin renderizar
        assert "{{" not in html, f"Template {name} dejó placeholder sin renderizar"
        assert "}}" not in html


def test_subjects_definidos_para_todos_los_templates():
    """Cada template debe tener un subject configurado."""
    for name in _TEMPLATES:
        assert name in _SUBJECTS, f"Template {name} sin subject"


def test_template_desconocido_lanza_error():
    """Pedir un template inexistente lanza ValueError."""
    with pytest.raises(ValueError):
        _render("template_que_no_existe", {})


def test_admin_recipients_se_juntan_con_to(monkeypatch):
    """Si hay NOTIFY_ADMIN_EMAILS, se concatenan al `to` sin duplicados."""
    from app.core import config as cfg_module
    monkeypatch.setattr(
        cfg_module.settings, "NOTIFY_ADMIN_EMAILS",
        "admin@x.com,ops@x.com",
    )
    subject, html, to_list = send_notification_sync_for_tests(
        "asignacion",
        {"codigo": "LAP-001", "persona_nombre": "Test"},
        to=["alice@test.local"],
    )
    assert "alice@test.local" in to_list
    assert "admin@x.com" in to_list
    assert "ops@x.com" in to_list
    # Sin duplicados
    assert len(to_list) == len(set(to_list))


def test_admin_recipients_sin_admins_solo_to(monkeypatch):
    """Si NOTIFY_ADMIN_EMAILS está vacío, solo `to`."""
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "NOTIFY_ADMIN_EMAILS", "")
    _, _, to_list = send_notification_sync_for_tests(
        "asignacion",
        {"codigo": "LAP-001", "persona_nombre": "Test"},
        to=["only-alice@test.local"],
    )
    assert to_list == ["only-alice@test.local"]


@pytest.mark.asyncio
async def test_asignacion_funciona_aunque_smtp_no_este(
    client, auth_headers, domain_seed,
):
    """
    El requisito crítico: si SMTP_HOST está vacío (caso de tests), la
    asignación NO debe fallar — el envío debe ser best-effort.
    """
    d = domain_seed
    r = await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_1"], "PER_Persona": d["alice"],
            "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_offboarding_funciona_aunque_smtp_no_este(
    client, auth_headers, domain_seed,
):
    """Offboarding también es best-effort respecto a SMTP."""
    d = domain_seed
    await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_1"], "PER_Persona": d["alice"],
            "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
        },
        headers=auth_headers,
    )
    r = await client.post(
        f"/api/v1/trazabilidad/persona/{d['alice']}/offboarding",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text


def test_template_html_no_inyecta_input_sin_escapar():
    """
    Jinja2 con autoescape=True evita XSS en el HTML. Probamos que un payload
    con `<script>` queda escapado.
    """
    subject, html = _render("asignacion", {
        "codigo": "<script>alert(1)</script>",
        "serie": "x", "tipo": "x", "marca": "x", "modelo": "x",
        "hostname": "", "persona_nombre": "x", "fecha": "x", "area": "x",
        "observacion": "",
    })
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
