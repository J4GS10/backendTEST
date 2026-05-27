"""
Tests del flujo de offboarding atómico. Valida que en una sola transacción:
  - Se cierran TODOS los movimientos vigentes de la persona
  - Cada activo liberado pasa a 'En Bodega'
  - Si la persona tiene usuario, se desactiva y todos sus tokens se revocan
  - PER_Estado pasa a false
  - Se registra un evento OFFBOARDING en audit log con snapshot
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.core import Activo
from app.models.governance import AuditoriaSistema, TokenRevocado
from app.models.organization import Persona, Usuario
from app.models.traceability import Movimiento


def _u(v):
    return uuid.UUID(v) if isinstance(v, str) else v


@pytest.mark.asyncio
async def test_offboarding_libera_todos_los_activos(
    client, auth_headers, domain_seed, session,
):
    """Persona con 2 activos asignados → tras offboarding, ambos en bodega."""
    d = domain_seed
    # Asignar 2 activos a alice
    for act_id in (d["act_1"], d["act_2"]):
        await client.post(
            "/api/v1/trazabilidad/movimientos",
            json={
                "ACT_Activo": act_id, "PER_Persona": d["alice"],
                "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
            },
            headers=auth_headers,
        )

    r = await client.post(
        f"/api/v1/trazabilidad/persona/{d['alice']}/offboarding",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["movimientos_cerrados"] == 2
    assert body["activos_devueltos_a_bodega"] == 2
    assert body["persona_inactivada"] is True

    # Verificar BD (expire para ver cambios de la otra sesión)
    session.expire_all()
    for act_id in (d["act_1"], d["act_2"]):
        estado = (await session.execute(
            select(Activo.EOP_Estado_Operativo).where(Activo.ACT_Activo == _u(act_id))
        )).scalar()
        assert estado == d["eop_bod"], (
            f"Activo {act_id} debió quedar En Bodega tras offboarding"
        )
    # Persona inactiva
    per = (await session.execute(
        select(Persona).where(Persona.PER_Persona == _u(d["alice"]))
    )).scalar_one()
    assert per.PER_Estado is False
    # 0 movimientos abiertos
    abiertos = (await session.execute(
        select(Movimiento).where(
            Movimiento.PER_Persona == _u(d["alice"]),
            Movimiento.MOV_Fecha_Devolucion.is_(None),
        )
    )).scalars().all()
    assert len(abiertos) == 0


@pytest.mark.asyncio
async def test_offboarding_desactiva_usuario_y_revoca_tokens(
    client, auth_headers, domain_seed, session,
):
    """
    Si la persona tiene un usuario asociado, el offboarding lo desactiva y
    registra una revocación global en SYS_TOKEN_REVOCADO con jti USR-ALL-{id}.
    """
    from app.core.security import get_password_hash
    d = domain_seed
    # Crear usuario para alice
    u = Usuario(
        USU_Username="alice_user",
        USU_Password_Hash=get_password_hash("Pass1234!ok"),
        USU_Rol="CONSULTA",
        PER_Persona=_u(d["alice"]),
    )
    session.add(u)
    await session.commit()

    r = await client.post(
        f"/api/v1/trazabilidad/persona/{d['alice']}/offboarding?desactivar_usuario=true",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["usuario_desactivado"] is True

    # Forzar refresco: la sesión del test mantenía el Usuario cached y no
    # veía el UPDATE hecho por la sesión del endpoint.
    session.expire_all()
    u2 = (await session.execute(
        select(Usuario).where(Usuario.USU_Username == "alice_user")
    )).scalar_one()
    assert u2.USU_Estado is False

    # Hay revocación global "USR-ALL-{uuid}"
    rev = (await session.execute(
        select(TokenRevocado).where(TokenRevocado.USU_Usuario == u2.USU_Usuario)
    )).scalars().all()
    assert any(r.TRV_Jti.startswith("USR-ALL-") for r in rev), \
        "Debe existir una revocación global tras offboarding"


@pytest.mark.asyncio
async def test_offboarding_es_idempotente(client, auth_headers, domain_seed, session):
    """
    Llamar offboarding dos veces seguidas no debe duplicar audit events ni romper.
    La segunda invocación debe ser noop (movimientos_cerrados=0).
    """
    d = domain_seed
    # Sin asignaciones previas, alice ya está activa
    r1 = await client.post(
        f"/api/v1/trazabilidad/persona/{d['alice']}/offboarding",
        headers=auth_headers,
    )
    assert r1.status_code == 200, r1.text
    r2 = await client.post(
        f"/api/v1/trazabilidad/persona/{d['alice']}/offboarding",
        headers=auth_headers,
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    # La segunda llamada no debe cerrar más movimientos
    assert body2["movimientos_cerrados"] == 0
    assert body2["idempotent_noop"] is True


@pytest.mark.asyncio
async def test_offboarding_protege_ultimo_super_admin(
    client, auth_headers, sa_user,
):
    """
    NO se permite offboarding del último SUPER_ADMIN — si lo permite,
    el sistema queda sin admin y la BD inaccesible administrativamente.
    """
    r = await client.post(
        f"/api/v1/trazabilidad/persona/{sa_user.PER_Persona}/offboarding"
        f"?desactivar_usuario=true",
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "CANNOT_OFFBOARD_LAST_SUPER_ADMIN"


@pytest.mark.asyncio
async def test_offboarding_registra_audit_event(
    client, auth_headers, domain_seed, session,
):
    """Cada offboarding efectivo deja un evento OFFBOARDING en audit log."""
    d = domain_seed
    await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_1"], "PER_Persona": d["alice"],
            "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
        },
        headers=auth_headers,
    )
    await client.post(
        f"/api/v1/trazabilidad/persona/{d['alice']}/offboarding",
        headers=auth_headers,
    )
    await session.commit()
    events = (await session.execute(
        select(AuditoriaSistema)
        .where(AuditoriaSistema.AUD_Accion == "OFFBOARDING")
    )).scalars().all()
    assert len(events) >= 1
    snap = events[-1].AUD_Snapshot_JSON
    assert snap.get("persona_id") == d["alice"]
    assert snap.get("activos_devueltos") == 1
