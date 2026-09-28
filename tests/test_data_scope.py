"""
Alcance de datos por sede (RLS) — capa de aplicación.

Escenario: sede A (la del domain_seed) y sede B. Un TECNICO/AUDITOR con alcance
solo sobre A no debe ver, modificar ni recibir sugerencias de datos de B. Cada
petición pasa por las dos capas: filtro de la aplicación y políticas RLS de
PostgreSQL (la base sola se prueba en test_data_scope_postgres.py).
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import select, update

from app.core.security import get_password_hash
from app.models.core import Activo
from app.models.governance import AuditoriaSistema
from app.models.organization import Persona, Usuario, UsuarioSede
from tests.conftest import crear_sede

FORM = {"Content-Type": "application/x-www-form-urlencoded"}
PWD = "Kx7!Alcance#Q"


async def _mk_user(session, username, role, *, sedes=(), global_=False):
    ref = (await session.execute(select(Persona))).scalars().first()
    per = Persona(PER_Primer_Nombre=username.title(), PER_Primer_Apellido="Scope",
                  PER_Email_Corporativo=f"{username}@empresa.local",
                  DEP_Departamento=ref.DEP_Departamento, CAR_Cargo=ref.CAR_Cargo,
                  SED_Sede=sedes[0] if sedes else None)
    session.add(per)
    await session.flush()
    usu = Usuario(USU_Username=username, USU_Password_Hash=get_password_hash(PWD), USU_Rol=role,
                  PER_Persona=per.PER_Persona, USU_Alcance_Global=global_)
    session.add(usu)
    await session.flush()
    for s in sedes:
        session.add(UsuarioSede(USU_Usuario=usu.USU_Usuario, SED_Sede=s))
    await session.commit()
    return usu, per


async def _h(client, username):
    r = await client.post("/api/v1/login/access-token", data={"username": username, "password": PWD},
                          headers=FORM)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def dos_sedes(session, domain_seed):
    """Sede A (domain_seed, con act_1/act_2/alice) y sede B (act_b, carol)."""
    sede_a, area_a = domain_seed["sede"], domain_seed["area"]
    b = await crear_sede(session, "Sede B")
    await session.execute(update(Activo).values(SED_Sede=sede_a))
    await session.execute(update(Persona).where(Persona.PER_Email_Corporativo.in_(
        ["alice@test.local", "bob@test.local"])).values(SED_Sede=sede_a))
    ref = (await session.execute(select(Persona))).scalars().first()
    carol = Persona(PER_Primer_Nombre="Carol", PER_Primer_Apellido="SedeB",
                    PER_Email_Corporativo="carol@test.local", DEP_Departamento=ref.DEP_Departamento,
                    CAR_Cargo=ref.CAR_Cargo, SED_Sede=b["sede"])
    act_b = Activo(ACT_Codigo_Interno="LAP-B01", ACT_Serie_Fabricante="SER-B01",
                   ACT_Fecha_Compra=date(2024, 3, 1), MOD_Modelo=domain_seed["mod"],
                   TAC_Tipo_Activo=domain_seed["tac_lap"], EOP_Estado_Operativo=domain_seed["eop_disp"],
                   SED_Sede=b["sede"])
    session.add_all([carol, act_b])
    await session.commit()
    return {**domain_seed, "sede_a": sede_a, "area_a": area_a, "sede_b": b["sede"], "area_b": b["area"],
            "carol": str(carol.PER_Persona), "act_b": str(act_b.ACT_Activo)}


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tecnico_solo_ve_activos_de_su_sede(client, session, dos_sedes):
    await _mk_user(session, "tec_a", "TECNICO", sedes=[dos_sedes["sede_a"]])
    h = await _h(client, "tec_a")

    r = await client.post("/api/v1/core/activos/search", headers=h, json={"page": 1, "per_page": 50})
    assert r.status_code == 200, r.text
    codigos = {a["ACT_Codigo_Interno"] for a in r.json()["items"]}
    assert codigos == {"LAP-001", "LAP-002"}
    assert r.json()["total"] == 2

    # Detalle y búsqueda por código de un activo de B: 404 (no revela que existe).
    assert (await client.get(f"/api/v1/core/activos/{dos_sedes['act_b']}", headers=h)).status_code == 404
    assert (await client.get("/api/v1/core/activos/by-code/LAP-B01", headers=h)).status_code == 404


@pytest.mark.asyncio
async def test_global_ve_todo(client, session, dos_sedes, auth_headers):
    r = await client.post("/api/v1/core/activos/search", headers=auth_headers, json={"page": 1, "per_page": 50})
    assert {a["ACT_Codigo_Interno"] for a in r.json()["items"]} >= {"LAP-001", "LAP-002", "LAP-B01"}


@pytest.mark.asyncio
async def test_sin_sedes_no_ve_nada(client, session, dos_sedes):
    await _mk_user(session, "tec_sin", "TECNICO")
    h = await _h(client, "tec_sin")
    r = await client.post("/api/v1/core/activos/search", headers=h, json={"page": 1, "per_page": 50})
    assert r.status_code == 200 and r.json()["total"] == 0
    assert (await client.get("/api/v1/org/personas", headers=h)).json() == [] or all(
        p["PER_Email_Corporativo"] == "tec_sin@empresa.local"
        for p in (await client.get("/api/v1/org/personas", headers=h)).json()
    )


@pytest.mark.asyncio
async def test_padron_de_personas_por_sede(client, session, dos_sedes):
    await _mk_user(session, "tec_a2", "TECNICO", sedes=[dos_sedes["sede_a"]])
    h = await _h(client, "tec_a2")
    emails = {p["PER_Email_Corporativo"] for p in (await client.get("/api/v1/org/personas", headers=h)).json()}
    assert "alice@test.local" in emails and "carol@test.local" not in emails
    assert (await client.get(f"/api/v1/org/personas/{dos_sedes['carol']}", headers=h)).status_code == 404


@pytest.mark.asyncio
async def test_sedes_en_alcance(client, session, dos_sedes):
    await _mk_user(session, "tec_a3", "TECNICO", sedes=[dos_sedes["sede_a"]])
    h = await _h(client, "tec_a3")
    sedes = (await client.get("/api/v1/org/sedes", headers=h)).json()
    assert [s["SED_Sede"] for s in sedes] == [dos_sedes["sede_a"]]
    areas = await client.get("/api/v1/geo/areas/all", headers=h)
    assert areas.status_code == 200
    assert {a["ARE_Area"] for a in areas.json()} == {dos_sedes["area_a"]}
    me = (await client.get("/api/v1/me", headers=h)).json()
    assert me["scope"] == {"global": False, "sedes": [{"id": dos_sedes["sede_a"], "nombre": "Oficina GDL"}]}


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_alta_de_activo_usa_su_sede_y_rechaza_otra(client, session, dos_sedes):
    await _mk_user(session, "tec_w", "TECNICO", sedes=[dos_sedes["sede_a"]])
    h = await _h(client, "tec_w")
    base = {"ACT_Serie_Fabricante": "SER-NEW-1", "ACT_Fecha_Compra": "2025-01-10",
            "MOD_Modelo": dos_sedes["mod"], "TAC_Tipo_Activo": dos_sedes["tac_lap"],
            "EOP_Estado_Operativo": dos_sedes["eop_disp"], "ACT_Codigo_Interno": "LAP-NEW-1"}
    r = await client.post("/api/v1/core/activos", headers=h, json=base)
    assert r.status_code == 201, r.text
    assert r.json()["SED_Sede"] == dos_sedes["sede_a"]  # su única sede, sin indicarla

    r = await client.post("/api/v1/core/activos", headers=h, json={
        **base, "ACT_Serie_Fabricante": "SER-NEW-2", "ACT_Codigo_Interno": "LAP-NEW-2",
        "SED_Sede": dos_sedes["sede_b"]})
    assert r.status_code == 403 and r.json()["detail"] == "SEDE_OUT_OF_SCOPE"

    # La serie es única en toda la empresa aunque el activo esté en otra sede.
    r = await client.post("/api/v1/core/activos", headers=h, json={
        **base, "ACT_Serie_Fabricante": "SER-B01", "ACT_Codigo_Interno": "LAP-NEW-3"})
    assert r.status_code == 400 and r.json()["detail"] == "SERIAL_NUMBER_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_asignacion_solo_a_areas_del_alcance(client, session, dos_sedes):
    await _mk_user(session, "tec_mov", "TECNICO", sedes=[dos_sedes["sede_a"]])
    h = await _h(client, "tec_mov")
    mov = {"ACT_Activo": dos_sedes["act_1"], "PER_Persona": dos_sedes["alice"],
           "TMO_Tipo_Movimiento": dos_sedes["tmo_asg"]}
    r = await client.post("/api/v1/trazabilidad/movimientos", headers=h, json={**mov, "ARE_Area": dos_sedes["area_b"]})
    assert r.status_code == 403 and r.json()["detail"] == "SEDE_OUT_OF_SCOPE"
    r = await client.post("/api/v1/trazabilidad/movimientos", headers=h, json={**mov, "ARE_Area": dos_sedes["area_a"]})
    assert r.status_code in (200, 201), r.text
    # Activo de otra sede: no existe para él.
    r = await client.post("/api/v1/trazabilidad/movimientos", headers=h, json={
        **mov, "ACT_Activo": dos_sedes["act_b"], "ARE_Area": dos_sedes["area_a"]})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_la_sede_del_activo_sigue_al_area(client, session, dos_sedes):
    await _mk_user(session, "tec_ab", "TECNICO", sedes=[dos_sedes["sede_a"], dos_sedes["sede_b"]])
    h = await _h(client, "tec_ab")
    r = await client.post("/api/v1/trazabilidad/movimientos", headers=h, json={
        "ACT_Activo": dos_sedes["act_1"], "PER_Persona": dos_sedes["carol"],
        "ARE_Area": dos_sedes["area_b"], "TMO_Tipo_Movimiento": dos_sedes["tmo_asg"]})
    assert r.status_code in (200, 201), r.text
    session.expire_all()
    act = (await session.execute(select(Activo).where(Activo.ACT_Activo == uuid.UUID(dos_sedes["act_1"])))).scalar_one()
    assert act.SED_Sede == dos_sedes["sede_b"]
    # Un técnico solo de A ya no lo ve.
    await _mk_user(session, "tec_solo_a", "TECNICO", sedes=[dos_sedes["sede_a"]])
    h_a = await _h(client, "tec_solo_a")
    assert (await client.get(f"/api/v1/core/activos/{dos_sedes['act_1']}", headers=h_a)).status_code == 404


@pytest.mark.asyncio
async def test_offboarding_parcial_bloqueado(client, session, dos_sedes, auth_headers, monkeypatch):
    # Alice (sede A) tiene un activo en B asignado por un global.
    r = await client.post("/api/v1/trazabilidad/movimientos", headers=auth_headers, json={
        "ACT_Activo": dos_sedes["act_b"], "PER_Persona": dos_sedes["alice"],
        "ARE_Area": dos_sedes["area_b"], "TMO_Tipo_Movimiento": dos_sedes["tmo_asg"]})
    assert r.status_code in (200, 201), r.text
    monkeypatch.setattr("app.core.config.settings.TWO_FACTOR_REQUIRED_ROLES", "SUPER_ADMIN")
    await _mk_user(session, "admti_a", "ADMIN_TI", sedes=[dos_sedes["sede_a"]])
    h = await _h(client, "admti_a")
    r = await client.post(f"/api/v1/trazabilidad/persona/{dos_sedes['alice']}/offboarding", headers=h)
    assert r.status_code == 403 and r.json()["detail"] == "OFFBOARDING_REQUIRES_SCOPE_OVER_ALL_ASSETS"


@pytest.mark.asyncio
async def test_geo_jerarquia_compartida_solo_global(client, session, dos_sedes, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.TWO_FACTOR_REQUIRED_ROLES", "SUPER_ADMIN")
    await _mk_user(session, "admti_geo", "ADMIN_TI", sedes=[dos_sedes["sede_a"]])
    h = await _h(client, "admti_geo")
    r = await client.post("/api/v1/geo/paises", headers=h, json={"PAI_Nombre": "Nuevo", "PAI_Codigo_ISO": "NV"})
    assert r.status_code == 403 and r.json()["detail"] == "GLOBAL_SCOPE_REQUIRED"
    r = await client.post("/api/v1/geo/edificios", headers=h, json={"EDI_Nombre": "Torre", "SED_Sede": dos_sedes["sede_b"]})
    assert r.status_code == 403
    r = await client.post("/api/v1/geo/edificios", headers=h, json={"EDI_Nombre": "Torre", "SED_Sede": dos_sedes["sede_a"]})
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------------------
# Autocompletado
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sugerencias_respetan_alcance(client, session, dos_sedes, auth_headers):
    # Historial de Alice: último movimiento en B (lo registra un global).
    r = await client.post("/api/v1/trazabilidad/movimientos", headers=auth_headers, json={
        "ACT_Activo": dos_sedes["act_b"], "PER_Persona": dos_sedes["alice"],
        "ARE_Area": dos_sedes["area_b"], "TMO_Tipo_Movimiento": dos_sedes["tmo_asg"]})
    assert r.status_code in (200, 201), r.text

    await _mk_user(session, "tec_sug", "TECNICO", sedes=[dos_sedes["sede_a"]])
    h = await _h(client, "tec_sug")
    ctx = (await client.get(f"/api/v1/org/personas/{dos_sedes['alice']}/contexto", headers=h)).json()
    # Nunca se sugiere un área fuera del alcance ni se revelan activos de B.
    assert ctx["area_sugerida"] is None or ctx["area_sugerida"]["SED_Sede"] == dos_sedes["sede_a"]
    assert "LAP-B01" not in ctx["activos_vigentes"]
    assert ctx["sede_sugerida"]["SED_Sede"] == dos_sedes["sede_a"]
    # Los datos de cuenta solo los ve quien gestiona identidades.
    assert ctx["usuario"] is None and ctx["rol_sugerido"] is None and ctx["username_sugerido"] is None

    # El global sí recibe el área real y el alcance sugerido (mínimo privilegio: su sede).
    ctx_sa = (await client.get(f"/api/v1/org/personas/{dos_sedes['alice']}/contexto", headers=auth_headers)).json()
    assert ctx_sa["area_sugerida"]["SED_Sede"] == dos_sedes["sede_b"]
    assert ctx_sa["alcance_sugerido"] == {"sedes": [dos_sedes["sede_a"]], "origen": "persona"}


# ---------------------------------------------------------------------------
# Auditor
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_auditor_lee_bitacora_de_su_sede_y_no_escribe(client, session, dos_sedes):
    session.add_all([
        AuditoriaSistema(AUD_Accion="UPDATE", AUD_Entidad_Afectada="INV_ACTIVO", AUD_Sede=dos_sedes["sede_a"]),
        AuditoriaSistema(AUD_Accion="UPDATE", AUD_Entidad_Afectada="INV_ACTIVO", AUD_Sede=dos_sedes["sede_b"]),
        AuditoriaSistema(AUD_Accion="LOGIN_SUCCESS", AUD_Entidad_Afectada="INV_USUARIO"),
    ])
    await session.commit()
    await _mk_user(session, "aud_a", "AUDITOR", sedes=[dos_sedes["sede_a"]])
    h = await _h(client, "aud_a")
    r = await client.get("/api/v1/gov/auditoria", headers=h, params={"entidad": "INV_ACTIVO"})
    assert r.status_code == 200, r.text
    assert {i["AUD_Sede"] for i in r.json()["items"]} == {dos_sedes["sede_a"]}
    # Lectura del inventario de su sede, sin escritura.
    assert (await client.post("/api/v1/core/activos/search", headers=h, json={"page": 1})).json()["total"] == 2
    r = await client.post("/api/v1/core/activos", headers=h, json={
        "ACT_Serie_Fabricante": "X-1", "ACT_Fecha_Compra": "2025-01-01", "MOD_Modelo": dos_sedes["mod"],
        "TAC_Tipo_Activo": dos_sedes["tac_lap"], "EOP_Estado_Operativo": dos_sedes["eop_disp"]})
    assert r.status_code == 403
    # Exporta la bitácora filtrada y la exportación queda registrada.
    csv = await client.get("/api/v1/gov/auditoria.csv", headers=h)
    assert csv.status_code == 200, csv.text
    eventos = (await session.execute(
        select(AuditoriaSistema).where(AuditoriaSistema.AUD_Accion == "AUDIT_EXPORT"))).scalars().all()
    assert len(eventos) == 1


# ---------------------------------------------------------------------------
# Administración del alcance
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_alcance_requerido_y_editable(client, session, dos_sedes, auth_headers):
    ref = (await session.execute(select(Persona))).scalars().first()
    p = Persona(PER_Primer_Nombre="Nuevo", PER_Primer_Apellido="Tec", PER_Email_Corporativo="nuevo.tec@empresa.local",
                DEP_Departamento=ref.DEP_Departamento, CAR_Cargo=ref.CAR_Cargo)
    session.add(p)
    await session.commit()
    body = {"USU_Username": "nuevo_tec", "USU_Password": PWD, "USU_Rol": "TECNICO", "PER_Persona": str(p.PER_Persona)}
    r = await client.post("/api/v1/org/usuarios", headers=auth_headers, json=body)
    assert r.status_code == 400 and r.json()["detail"] == "SCOPE_REQUIRED"
    r = await client.post("/api/v1/org/usuarios", headers=auth_headers, json={**body, "sedes": [dos_sedes["sede_a"]]})
    assert r.status_code == 201, r.text
    uid = r.json()["USU_Usuario"]
    r = await client.patch(f"/api/v1/org/usuarios/{uid}", headers=auth_headers,
                           json={"sedes": [dos_sedes["sede_a"], dos_sedes["sede_b"]]})
    assert r.status_code == 200 and {s["SED_Sede"] for s in r.json()["sedes"]} == {dos_sedes["sede_a"], dos_sedes["sede_b"]}
    audit = (await session.execute(select(AuditoriaSistema).where(
        AuditoriaSistema.AUD_Entidad_Afectada == "INV_USUARIO", AuditoriaSistema.AUD_Accion == "UPDATE"))).scalars().all()
    assert any("alcance" in (a.AUD_Snapshot_JSON or {}).get("diff", {}) for a in audit)
    r = await client.patch(f"/api/v1/org/usuarios/{uid}", headers=auth_headers, json={"sedes": [999999]})
    assert r.status_code == 400 and r.json()["detail"] == "SEDE_NOT_FOUND"


@pytest.mark.asyncio
async def test_licencia_a_persona_segun_alcance(client, session, dos_sedes, software_seed):
    """Instalaciones sin activo (a una persona): visibles y permitidas según la sede de la persona."""
    await _mk_user(session, "tec_sw", "TECNICO", sedes=[dos_sedes["sede_a"]])
    h = await _h(client, "tec_sw")
    base = {"LIC_Licencia": software_seed["lic"], "INS_Fecha_Instalacion": "2026-05-28"}
    r = await client.post("/api/v1/soft/instalaciones", headers=h, json={**base, "PER_Persona": dos_sedes["alice"]})
    assert r.status_code == 201, r.text
    # Carol es de la sede B: para él no existe.
    r = await client.post("/api/v1/soft/instalaciones", headers=h, json={**base, "PER_Persona": dos_sedes["carol"]})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_traslado_entre_sedes_se_audita_en_ambas(client, session, dos_sedes, auth_headers):
    r = await client.post("/api/v1/trazabilidad/movimientos", headers=auth_headers, json={
        "ACT_Activo": dos_sedes["act_1"], "PER_Persona": dos_sedes["carol"],
        "ARE_Area": dos_sedes["area_b"], "TMO_Tipo_Movimiento": dos_sedes["tmo_asg"]})
    assert r.status_code in (200, 201), r.text
    await _mk_user(session, "aud_origen", "AUDITOR", sedes=[dos_sedes["sede_a"]])
    h = await _h(client, "aud_origen")
    acciones = {i["AUD_Accion"] for i in (await client.get("/api/v1/gov/auditoria", headers=h)).json()["items"]}
    assert "ASSET_SEDE_CHANGE" in acciones  # el auditor de la sede de origen ve la salida


@pytest.mark.asyncio
async def test_tablero_para_lectura_y_con_alcance(client, session, dos_sedes, auth_headers):
    """AUDITOR y CONSULTA ven el tablero, calculado solo con su sede."""
    total_global = (await client.get("/api/v1/stats/dashboard", headers=auth_headers)).json()
    for username, rol in (("aud_tab", "AUDITOR"), ("con_tab", "CONSULTA")):
        await _mk_user(session, username, rol, sedes=[dos_sedes["sede_a"]])
        r = await client.get("/api/v1/stats/dashboard", headers=await _h(client, username))
        assert r.status_code == 200, (rol, r.text)
        assert r.json() != total_global  # la sede B no cuenta
