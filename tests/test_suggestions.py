"""Sugerencias relacionales para autocompletar formularios."""
import pytest
from sqlalchemy import select

from app.models.organization import Cargo, Persona, Usuario


@pytest.mark.asyncio
async def test_contexto_persona_y_activo(client, auth_headers, domain_seed, session):
    d = domain_seed
    # Alice recibe LAP-001 en el área del seed.
    r = await client.post("/api/v1/trazabilidad/movimientos", headers=auth_headers, json={
        "ACT_Activo": d["act_1"], "PER_Persona": d["alice"], "ARE_Area": d["area"],
        "TMO_Tipo_Movimiento": d["tmo_asg"]})
    assert r.status_code == 201, r.text

    ctx = (await client.get(f"/api/v1/org/personas/{d['alice']}/contexto", headers=auth_headers)).json()
    assert ctx["departamento"]["nombre"] == "Tecnología"
    assert ctx["cargo"]["nombre"] == "Ingeniero"
    assert ctx["area_sugerida"]["ARE_Area"] == d["area"] and ctx["area_sugerida"]["origen"] == "ultima_asignacion"
    assert ctx["activos_vigentes"] == ["LAP-001"]
    assert ctx["usuario"] is None
    assert ctx["username_sugerido"] == "alice"
    # Sin usuarios en su cargo/departamento: rol de mínimo privilegio.
    assert ctx["rol_sugerido"] == {"rol": "CONSULTA", "origen": "minimo_privilegio"}

    # Bob (mismo departamento, sin movimientos): área del departamento.
    bob = (await client.get(f"/api/v1/org/personas/{d['bob']}/contexto", headers=auth_headers)).json()
    assert bob["area_sugerida"]["origen"] == "departamento"

    act = (await client.get(f"/api/v1/core/activos/{d['act_1']}/contexto", headers=auth_headers)).json()
    assert act["custodio"]["nombre"] == "Alice Test"
    assert act["tipo_movimiento_sugerido"] == "transferencia"
    libre = (await client.get(f"/api/v1/core/activos/{d['act_2']}/contexto", headers=auth_headers)).json()
    assert libre["custodio"] is None and libre["tipo_movimiento_sugerido"] == "asignacion"


@pytest.mark.asyncio
async def test_rol_sugerido_por_cargo_nunca_privilegiado(client, auth_headers, domain_seed, session):
    from app.core.security import get_password_hash
    d = domain_seed
    alice = (await session.execute(select(Persona).where(Persona.PER_Email_Corporativo == "alice@test.local"))).scalar_one()
    session.add(Usuario(USU_Username="alice.ti", USU_Password_Hash=get_password_hash("x"), USU_Rol="TECNICO",
                        PER_Persona=alice.PER_Persona))
    await session.commit()
    bob = (await client.get(f"/api/v1/org/personas/{d['bob']}/contexto", headers=auth_headers)).json()
    assert bob["rol_sugerido"] == {"rol": "TECNICO", "origen": "cargo"}

    # Un rol privilegiado en el mismo cargo no se sugiere.
    alice_u = (await session.execute(select(Usuario).where(Usuario.USU_Username == "alice.ti"))).scalar_one()
    alice_u.USU_Rol = "ADMIN_SEGURIDAD"
    await session.commit()
    bob = (await client.get(f"/api/v1/org/personas/{d['bob']}/contexto", headers=auth_headers)).json()
    assert bob["rol_sugerido"]["rol"] != "ADMIN_SEGURIDAD"


@pytest.mark.asyncio
async def test_contexto_departamento_y_modelo(client, auth_headers, domain_seed, session):
    d = domain_seed
    cargo = (await session.execute(select(Cargo).where(Cargo.CAR_Nombre == "Ingeniero"))).scalar_one()
    dep = (await client.get(f"/api/v1/org/personas/{d['alice']}/contexto", headers=auth_headers)).json()["departamento"]
    ctx = (await client.get(f"/api/v1/org/departamentos/{dep['DEP_Departamento']}/contexto", headers=auth_headers)).json()
    assert ctx["cargo_sugerido"]["CAR_Cargo"] == cargo.CAR_Cargo

    m = (await client.get(f"/api/v1/cat/modelos/{d['mod']}/contexto", headers=auth_headers)).json()
    assert m["marca"]["MAR_Marca"] == d["mar"]
    assert m["tipo_sugerido"]["TAC_Tipo_Activo"] == d["tac_lap"]


@pytest.mark.asyncio
async def test_persona_no_puede_ser_su_propio_jefe(client, auth_headers, domain_seed):
    r = await client.patch(f"/api/v1/org/personas/{domain_seed['alice']}", headers=auth_headers,
                           json={"PER_Jefe": domain_seed["alice"]})
    assert r.status_code == 400 and r.json()["detail"] == "PERSON_CANNOT_BE_OWN_MANAGER"
    r = await client.patch(f"/api/v1/org/personas/{domain_seed['alice']}", headers=auth_headers,
                           json={"PER_Jefe": domain_seed["bob"]})
    assert r.status_code == 200 and r.json()["PER_Jefe"] == domain_seed["bob"]
