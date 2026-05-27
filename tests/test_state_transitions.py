"""
Tests de transición de estado operativo (EOP_Estado_Operativo) por cada
tipo de movimiento. Cubren el bug donde un activo asignado quedaba con
estado 'En Bodega' / 'Disponible' en lugar de 'Asignado'.

Regla a garantizar: INV_MOVIMIENTO e INV_ACTIVO.EOP_Estado_Operativo
nunca pueden quedar inconsistentes después de un commit del servicio.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.core import Activo
from app.models.traceability import Movimiento


def _u(v):
    """Helper: convierte str → uuid.UUID si hace falta (SQLite + SQLAlchemy UUID)."""
    return uuid.UUID(v) if isinstance(v, str) else v


async def _estado_activo(session, activo_id) -> int:
    """Lee el EOP_Estado_Operativo actual desde BD (sin cache)."""
    await session.commit()  # asegurar visibilidad de cambios de otra sesión
    row = (await session.execute(
        select(Activo.EOP_Estado_Operativo).where(Activo.ACT_Activo == _u(activo_id))
    )).first()
    return row[0] if row else None


async def _movimientos_abiertos(session, activo_id) -> int:
    await session.commit()
    rows = (await session.execute(
        select(Movimiento).where(
            Movimiento.ACT_Activo == _u(activo_id),
            Movimiento.MOV_Fecha_Devolucion.is_(None),
        )
    )).scalars().all()
    return len(rows)


@pytest.mark.asyncio
async def test_asignacion_transiciona_a_asignado(client, auth_headers, domain_seed, session):
    """Activo Disponible + ASIGNACIÓN → estado debe quedar 'Asignado'."""
    d = domain_seed
    r = await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_1"], "PER_Persona": d["alice"],
            "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
            "MOV_Observacion": "test asignación",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    estado = await _estado_activo(session, d["act_1"])
    assert estado == d["eop_asig"], (
        f"Activo asignado debe estar 'Asignado' (id={d['eop_asig']}), "
        f"pero está en id={estado}"
    )
    assert await _movimientos_abiertos(session, d["act_1"]) == 1


@pytest.mark.asyncio
async def test_devolucion_transiciona_a_bodega(client, auth_headers, domain_seed, session):
    """Activo Asignado + DEVOLUCIÓN → estado 'En Bodega' + movimiento cerrado."""
    d = domain_seed
    # Primero asignar
    await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_1"], "PER_Persona": d["alice"],
            "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
        },
        headers=auth_headers,
    )
    # Devolver
    r = await client.post(
        "/api/v1/trazabilidad/devolucion",
        json={"ACT_Activo": d["act_1"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    estado = await _estado_activo(session, d["act_1"])
    assert estado == d["eop_bod"], f"Esperado En Bodega ({d['eop_bod']}), obtenido {estado}"
    assert await _movimientos_abiertos(session, d["act_1"]) == 0


@pytest.mark.asyncio
async def test_prestamo_transiciona_a_asignado(client, auth_headers, domain_seed, session):
    """PRÉSTAMO debe comportarse igual que asignación para el estado."""
    d = domain_seed
    r = await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_2"], "PER_Persona": d["alice"],
            "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_pres"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    estado = await _estado_activo(session, d["act_2"])
    assert estado == d["eop_asig"]


@pytest.mark.asyncio
async def test_transferencia_mantiene_asignado(client, auth_headers, domain_seed, session):
    """TRANSFERENCIA cambia el destinatario pero el activo sigue 'Asignado'."""
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
        "/api/v1/trazabilidad/transferencia",
        json={
            "ACT_Activo": d["act_1"],
            "PER_Persona_Destino": d["bob"],
            "ARE_Area_Destino": d["area"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    estado = await _estado_activo(session, d["act_1"])
    assert estado == d["eop_asig"], "Transferencia debe mantener Asignado"
    assert await _movimientos_abiertos(session, d["act_1"]) == 1


@pytest.mark.asyncio
async def test_no_se_puede_asignar_activo_de_baja(client, auth_headers, domain_seed, session):
    """Activo en estado Baja NO puede ser asignado."""
    d = domain_seed
    # Forzar el activo a Baja en BD directamente
    from sqlalchemy import update
    await session.execute(
        update(Activo).where(Activo.ACT_Activo == _u(d["act_1"])).values(EOP_Estado_Operativo=d["eop_baja"])
    )
    await session.commit()

    r = await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_1"], "PER_Persona": d["alice"],
            "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "CANNOT_ASSIGN_DECOMMISSIONED_ASSET"


@pytest.mark.asyncio
async def test_re_asignacion_cierra_movimiento_previo(client, auth_headers, domain_seed, session):
    """
    Asignar a alice + asignar de nuevo a bob debe cerrar el primer movimiento
    y dejar UN SOLO movimiento abierto (el de bob), con estado 'Asignado'.
    """
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
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_1"], "PER_Persona": d["bob"],
            "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
        },
        headers=auth_headers,
    )
    assert await _movimientos_abiertos(session, d["act_1"]) == 1
    estado = await _estado_activo(session, d["act_1"])
    assert estado == d["eop_asig"]


@pytest.mark.asyncio
async def test_devolucion_falla_si_no_hay_asignacion(client, auth_headers, domain_seed):
    """Devolver un activo que nunca fue asignado debe fallar 400."""
    d = domain_seed
    r = await client.post(
        "/api/v1/trazabilidad/devolucion",
        json={"ACT_Activo": d["act_2"]},
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "ASSET_IS_NOT_ASSIGNED"
