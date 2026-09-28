"""Pruebas ACID de rollback en flujos criticos de negocio."""
import uuid

import pytest
from sqlalchemy import func, select, update

from app.models.catalogs import EstadoOperativo
from app.models.core import Activo
from app.models.governance import AuditoriaSistema
from app.models.organization import Persona
from app.models.traceability import Movimiento


def _u(value):
    return uuid.UUID(value) if isinstance(value, str) else value


@pytest.mark.asyncio
async def test_asignacion_rollback_si_estado_destino_no_existe(
    client, auth_headers, domain_seed, session,
):
    """
    Si falla la transicion de estado despues de crear el movimiento en memoria,
    la transaccion completa debe revertirse: sin movimiento abierto y sin cambio
    de estado del activo.
    """
    d = domain_seed
    await session.execute(
        update(EstadoOperativo)
        .where(EstadoOperativo.EOP_Estado_Operativo == d["eop_asig"])
        .values(EOP_Nombre="Estado destino removido")
    )
    await session.commit()

    r = await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_1"],
            "PER_Persona": d["alice"],
            "ARE_Area": d["area"],
            "TMO_Tipo_Movimiento": d["tmo_asg"],
            "ACT_Hostname": "hostname-no-debe-persistir",
        },
        headers=auth_headers,
    )

    assert r.status_code == 500
    assert r.json()["detail"] == "SYSTEM_CONFIG_ERROR_MISSING_OPERATIONAL_STATE"

    session.expire_all()
    abiertos = (await session.execute(
        select(func.count())
        .select_from(Movimiento)
        .where(
            Movimiento.ACT_Activo == _u(d["act_1"]),
            Movimiento.MOV_Fecha_Devolucion.is_(None),
        )
    )).scalar_one()
    assert abiertos == 0

    activo = (await session.execute(
        select(Activo).where(Activo.ACT_Activo == _u(d["act_1"]))
    )).scalar_one()
    assert activo.EOP_Estado_Operativo == d["eop_disp"]
    assert activo.ACT_Hostname == "laptop-1"


@pytest.mark.asyncio
async def test_offboarding_rollback_si_estado_bodega_no_existe(
    client, auth_headers, domain_seed, session,
):
    """
    Offboarding es atomico: si no puede mover activos a bodega, no debe cerrar
    movimientos, inactivar la persona ni auditar un evento efectivo.
    """
    d = domain_seed
    asignacion = await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_1"],
            "PER_Persona": d["alice"],
            "ARE_Area": d["area"],
            "TMO_Tipo_Movimiento": d["tmo_asg"],
        },
        headers=auth_headers,
    )
    assert asignacion.status_code == 201, asignacion.text

    await session.execute(
        update(EstadoOperativo)
        .where(EstadoOperativo.EOP_Estado_Operativo == d["eop_bod"])
        .values(EOP_Nombre="Almacen")
    )
    await session.commit()

    r = await client.post(
        f"/api/v1/trazabilidad/persona/{d['alice']}/offboarding",
        headers=auth_headers,
    )

    assert r.status_code == 500
    assert r.json()["detail"] == "SYSTEM_CONFIG_ERROR_MISSING_OPERATIONAL_STATE"

    session.expire_all()
    movimiento = (await session.execute(
        select(Movimiento).where(
            Movimiento.ACT_Activo == _u(d["act_1"]),
            Movimiento.PER_Persona == _u(d["alice"]),
        )
    )).scalar_one()
    assert movimiento.MOV_Fecha_Devolucion is None

    activo = (await session.execute(
        select(Activo).where(Activo.ACT_Activo == _u(d["act_1"]))
    )).scalar_one()
    assert activo.EOP_Estado_Operativo == d["eop_asig"]

    persona = (await session.execute(
        select(Persona).where(Persona.PER_Persona == _u(d["alice"]))
    )).scalar_one()
    assert persona.PER_Estado is True

    audit_count = (await session.execute(
        select(func.count())
        .select_from(AuditoriaSistema)
        .where(AuditoriaSistema.AUD_Accion == "OFFBOARDING")
    )).scalar_one()
    assert audit_count == 0
