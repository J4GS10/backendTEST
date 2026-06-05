"""
Tests de las mejoras de seguridad de la auditoría 2026-06-01:
  - Rotación de refresh token + detección de reuso.
  - Auditoría de eventos de autenticación (LOGIN_SUCCESS / LOGIN_FAILED).
  - Respuesta uniforme anti-enumeración de usuarios.
"""
import pytest
from sqlalchemy import select

from app.models.governance import AuditoriaSistema


async def _login(client, username="sa", password="TestPassw0rd!"):
    return await client.post(
        "/api/v1/login/access-token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


@pytest.mark.asyncio
async def test_refresh_rotates_and_detects_reuse(client, sa_user):
    """El refresh token se rota en cada uso; reusar el viejo → 401."""
    r = await _login(client)
    assert r.status_code == 200
    old_refresh = r.json()["refresh_token"]

    # Primer uso: OK y devuelve un refresh NUEVO (distinto del usado).
    r1 = await client.post("/api/v1/login/refresh", json={"refresh_token": old_refresh})
    assert r1.status_code == 200, r1.text
    new_refresh = r1.json().get("refresh_token")
    assert new_refresh and new_refresh != old_refresh

    # Reuso del refresh viejo → revocado por la rotación.
    r2 = await client.post("/api/v1/login/refresh", json={"refresh_token": old_refresh})
    assert r2.status_code == 401
    assert r2.json()["detail"] == "TOKEN_REVOKED"

    # El refresh nuevo sigue siendo válido.
    r3 = await client.post("/api/v1/login/refresh", json={"refresh_token": new_refresh})
    assert r3.status_code == 200


@pytest.mark.asyncio
async def test_login_success_is_audited(client, sa_user, session):
    await _login(client)
    rows = (await session.execute(
        select(AuditoriaSistema).where(AuditoriaSistema.AUD_Accion == "LOGIN_SUCCESS")
    )).scalars().all()
    assert len(rows) >= 1


@pytest.mark.asyncio
async def test_failed_login_is_audited(client, sa_user, session):
    await _login(client, password="definitely-wrong")
    rows = (await session.execute(
        select(AuditoriaSistema).where(AuditoriaSistema.AUD_Accion == "LOGIN_FAILED")
    )).scalars().all()
    assert len(rows) >= 1
    assert rows[-1].AUD_Snapshot_JSON.get("reason") == "bad_password"


@pytest.mark.asyncio
async def test_login_sets_httponly_refresh_cookie(client, sa_user):
    """El login setea el refresh token en una cookie HttpOnly."""
    r = await _login(client)
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "rtk=" in set_cookie
    assert "HttpOnly" in set_cookie


@pytest.mark.asyncio
async def test_refresh_works_with_cookie_only(client, sa_user):
    """Tras login, el refresh funciona usando SOLO la cookie (sin body)."""
    r = await _login(client)
    assert r.status_code == 200
    # El cliente httpx ya tiene la cookie rtk; refresh sin body.
    r1 = await client.post("/api/v1/login/refresh", json={})
    assert r1.status_code == 200, r1.text
    assert "access_token" in r1.json()


@pytest.mark.asyncio
async def test_cannot_rename_system_operational_state(client, auth_headers, domain_seed):
    """Renombrar un estado canónico (Asignado) debe rechazarse con 409."""
    r = await client.patch(
        f"/api/v1/cat/estados-operativos/{domain_seed['eop_asig']}",
        json={"EOP_Nombre": "Renombrado"},
        headers=auth_headers,
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "CANNOT_MODIFY_SYSTEM_OPERATIONAL_STATUS"


def test_internal_error_maps_integrity_to_409_else_500():
    """Consistencia: una violación de integridad nunca debe ser 500."""
    from app.core.errors import internal_error
    from sqlalchemy.exc import IntegrityError
    ie = IntegrityError("INSERT ...", {}, Exception("duplicate key"))
    assert internal_error(ie).status_code == 409
    assert internal_error(ie).detail == "INTEGRITY_CONSTRAINT_VIOLATED"
    # Cualquier otra excepción inesperada sigue siendo 500 (genérico).
    assert internal_error(ValueError("boom")).status_code == 500


@pytest.mark.asyncio
async def test_only_one_open_maintenance_per_asset_db_guard(domain_seed, session):
    """El índice único parcial impide 2 mantenimientos ABIERTOS para un activo
    (garantía de concurrencia a nivel BD, no solo el SELECT del servicio)."""
    import uuid
    from sqlalchemy.exc import IntegrityError
    from app.models.traceability import Mantenimiento, TipoMantenimiento
    tm = TipoMantenimiento(TMA_Nombre="Correctivo")
    session.add(tm)
    await session.flush()
    act = uuid.UUID(domain_seed["act_2"])
    per = uuid.UUID(domain_seed["alice"])
    session.add(Mantenimiento(
        ACT_Activo=act, PER_Persona_Solicita=per,
        TMA_Tipo_Mantenimiento=tm.TMA_Tipo_Mantenimiento, MAN_Descripcion_Falla="falla 1"))
    await session.flush()
    # Un segundo ticket ABIERTO para el mismo activo viola el índice único parcial.
    session.add(Mantenimiento(
        ACT_Activo=act, PER_Persona_Solicita=per,
        TMA_Tipo_Mantenimiento=tm.TMA_Tipo_Mantenimiento, MAN_Descripcion_Falla="falla 2"))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_patch_usuario_empty_body_is_noop_not_500(client, auth_headers, domain_seed, session):
    """Un PATCH con body vacío debe ser no-op (200), no romper con 500."""
    import uuid
    from sqlalchemy import select
    from app.models.organization import Persona
    alice = (await session.execute(
        select(Persona).where(Persona.PER_Persona == uuid.UUID(domain_seed["alice"])))).scalar_one()
    p = Persona(PER_Primer_Nombre="Pat", PER_Primer_Apellido="Tester",
                PER_Email_Corporativo="pat@example.com",
                DEP_Departamento=alice.DEP_Departamento, CAR_Cargo=alice.CAR_Cargo)
    session.add(p)
    await session.commit()
    cr = await client.post("/api/v1/org/usuarios", headers=auth_headers, json={
        "USU_Username": "pat_test", "USU_Password": "Patito#2026",
        "USU_Rol": "TECNICO", "PER_Persona": str(p.PER_Persona)})
    assert cr.status_code == 201, cr.text
    uid = cr.json()["USU_Usuario"]
    # PATCH vacío → no-op, debe devolver 200 (antes daba 500 por "SET  WHERE").
    r = await client.patch(f"/api/v1/org/usuarios/{uid}", headers=auth_headers, json={})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_delete_catalog_in_use_returns_409_not_500(client, auth_headers, domain_seed):
    """Borrar una marca con modelos asociados → 409 limpio (no 500 por FK)."""
    r = await client.delete(f"/api/v1/cat/marcas/{domain_seed['mar']}", headers=auth_headers)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "CANNOT_DELETE_BRAND_IN_USE"


@pytest.mark.asyncio
async def test_admin_ti_cannot_escalate_user_to_admin_roles(client, auth_headers, domain_seed, session):
    """Anti-escalada: un ADMIN_TI no puede otorgar roles administrativos vía PATCH."""
    import uuid
    from sqlalchemy import select
    from app.models.organization import Persona
    # Personas con emails válidos (el seed usa .local, rechazado por EmailStr).
    alice = (await session.execute(
        select(Persona).where(Persona.PER_Persona == uuid.UUID(domain_seed["alice"]))
    )).scalar_one()
    p_adm = Persona(PER_Primer_Nombre="Adm", PER_Primer_Apellido="Tester",
                    PER_Email_Corporativo="adm@example.com",
                    DEP_Departamento=alice.DEP_Departamento, CAR_Cargo=alice.CAR_Cargo)
    p_con = Persona(PER_Primer_Nombre="Con", PER_Primer_Apellido="Tester",
                    PER_Email_Corporativo="con@example.com",
                    DEP_Departamento=alice.DEP_Departamento, CAR_Cargo=alice.CAR_Cargo)
    session.add_all([p_adm, p_con])
    await session.commit()
    # sa crea un ADMIN_TI
    r = await client.post("/api/v1/org/usuarios", headers=auth_headers, json={
        "USU_Username": "adm_test", "USU_Password": "Escalada#2026",
        "USU_Rol": "ADMIN_TI", "PER_Persona": str(p_adm.PER_Persona)})
    assert r.status_code == 201, r.text
    lr = await client.post(
        "/api/v1/login/access-token",
        data={"username": "adm_test", "password": "Escalada#2026"},
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    adm = {"Authorization": f"Bearer {lr.json()['access_token']}"}
    # ese ADMIN_TI crea un CONSULTA
    cr = await client.post("/api/v1/org/usuarios", headers=adm, json={
        "USU_Username": "cons_test", "USU_Password": "Consulta#2026",
        "USU_Rol": "CONSULTA", "PER_Persona": str(p_con.PER_Persona)})
    assert cr.status_code == 201, cr.text
    cid = cr.json()["USU_Usuario"]
    # EXPLOIT bloqueado: ADMIN_TI no puede elevar a SUPER_ADMIN ni a ADMIN_TI
    ex = await client.patch(f"/api/v1/org/usuarios/{cid}", headers=adm, json={"USU_Rol": "SUPER_ADMIN"})
    assert ex.status_code == 403
    assert ex.json()["detail"] == "ONLY_SUPER_ADMIN_CAN_GRANT_ADMIN_ROLES"
    ex2 = await client.patch(f"/api/v1/org/usuarios/{cid}", headers=adm, json={"USU_Rol": "ADMIN_TI"})
    assert ex2.status_code == 403
    # Control positivo: un SUPER_ADMIN sí puede cambiar el rol (a uno no-admin)
    ok = await client.patch(f"/api/v1/org/usuarios/{cid}", headers=auth_headers, json={"USU_Rol": "TECNICO"})
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_role_change_is_audited_with_before_after_diff(client, auth_headers, domain_seed, session):
    """La bitácora del cambio de rol debe registrar el valor anterior y el nuevo."""
    import uuid
    from sqlalchemy import select
    from app.models.governance import AuditoriaSistema
    from app.models.organization import Persona

    alice = (await session.execute(
        select(Persona).where(Persona.PER_Persona == uuid.UUID(domain_seed["alice"]))
    )).scalar_one()
    p = Persona(PER_Primer_Nombre="Diff", PER_Primer_Apellido="Tester",
                PER_Email_Corporativo="diff@example.com",
                DEP_Departamento=alice.DEP_Departamento, CAR_Cargo=alice.CAR_Cargo)
    session.add(p)
    await session.commit()

    cr = await client.post("/api/v1/org/usuarios", headers=auth_headers, json={
        "USU_Username": "diff_test", "USU_Password": "Diferencia#2026",
        "USU_Rol": "CONSULTA", "PER_Persona": str(p.PER_Persona)})
    assert cr.status_code == 201, cr.text
    uid = cr.json()["USU_Usuario"]

    # SUPER_ADMIN reasigna el rol: CONSULTA -> TECNICO
    r = await client.patch(f"/api/v1/org/usuarios/{uid}", headers=auth_headers, json={"USU_Rol": "TECNICO"})
    assert r.status_code == 200, r.text

    # El último evento UPDATE sobre INV_USUARIO de ese target trae el diff antes->después.
    ev = (await session.execute(
        select(AuditoriaSistema)
        .where(AuditoriaSistema.AUD_Accion == "UPDATE",
               AuditoriaSistema.AUD_Entidad_Afectada == "INV_USUARIO")
        .order_by(AuditoriaSistema.AUD_Fecha_Hora.desc())
    )).scalars().first()
    assert ev is not None
    diff = ev.AUD_Snapshot_JSON.get("diff", {})
    assert diff.get("USU_Rol") == {"antes": "CONSULTA", "despues": "TECNICO"}
    assert ev.AUD_Snapshot_JSON.get("target_username") == "diff_test"


@pytest.mark.asyncio
async def test_nonexistent_user_same_response_as_bad_password(client, sa_user):
    """Usuario inexistente y password incorrecta devuelven el MISMO 400
    (no se filtra la existencia de la cuenta)."""
    r_missing = await _login(client, username="ghost_user_xyz", password="whatever1!")
    r_badpw = await _login(client, password="whatever1!")
    assert r_missing.status_code == r_badpw.status_code == 400
    assert (
        r_missing.json()["detail"]
        == r_badpw.json()["detail"]
        == "INCORRECT_USERNAME_OR_PASSWORD"
    )
