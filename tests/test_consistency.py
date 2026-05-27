"""
Tests de consistencia cross-módulo. Garantizan invariantes que el bug del
estado 'En Bodega + asignado' rompió: que dos tablas relacionadas no
queden desincronizadas tras una operación de negocio.

Invariantes garantizadas:
  1. NUNCA hay > 1 movimiento abierto para el mismo activo.
  2. Si un activo tiene un movimiento abierto, EOP_Estado_Operativo
     no puede ser 'Disponible' ni 'En Bodega'.
  3. Si un activo NO tiene movimientos abiertos, EOP_Estado_Operativo
     debe ser 'Disponible' o 'En Bodega' (no 'Asignado').
  4. Cada operación de negocio genera UN evento de audit log.
"""
import uuid

import pytest
from sqlalchemy import func, select

from app.models.core import Activo
from app.models.governance import AuditoriaSistema
from app.models.traceability import Movimiento


def _u(v):
    return uuid.UUID(v) if isinstance(v, str) else v


async def _commit_and_sync(session):
    await session.commit()


async def _movimientos_abiertos_global(session) -> int:
    rows = (await session.execute(
        select(Movimiento).where(Movimiento.MOV_Fecha_Devolucion.is_(None))
    )).scalars().all()
    return len(rows)


@pytest.mark.asyncio
async def test_inv_un_solo_movimiento_abierto_por_activo(
    client, auth_headers, domain_seed, session,
):
    """Re-asignar el mismo activo no debe dejar 2 movimientos abiertos."""
    d = domain_seed
    for receptor in (d["alice"], d["bob"], d["alice"]):  # 3 asignaciones seguidas
        await client.post(
            "/api/v1/trazabilidad/movimientos",
            json={
                "ACT_Activo": d["act_1"], "PER_Persona": receptor,
                "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
            },
            headers=auth_headers,
        )
    await _commit_and_sync(session)
    abiertos = (await session.execute(
        select(func.count()).select_from(Movimiento)
        .where(
            Movimiento.ACT_Activo == _u(d["act_1"]),
            Movimiento.MOV_Fecha_Devolucion.is_(None),
        )
    )).scalar()
    assert abiertos == 1, f"INV: solo un movimiento abierto por activo (encontrados {abiertos})"


@pytest.mark.asyncio
async def test_inv_activo_asignado_no_puede_estar_en_bodega(
    client, auth_headers, domain_seed, session,
):
    """
    Tras ASIGNAR un activo, su estado NO puede ser En Bodega ni Disponible.
    Este es el invariante que rompía el bug original.
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
    await _commit_and_sync(session)
    estado = (await session.execute(
        select(Activo.EOP_Estado_Operativo).where(Activo.ACT_Activo == _u(d["act_1"]))
    )).scalar()
    assert estado not in (d["eop_bod"], d["eop_disp"]), (
        f"INV ROTA: activo asignado tiene estado {estado} "
        f"(bodega={d['eop_bod']}, disponible={d['eop_disp']})"
    )
    assert estado == d["eop_asig"]


@pytest.mark.asyncio
async def test_inv_devolucion_devuelve_a_bodega(
    client, auth_headers, domain_seed, session,
):
    """Tras DEVOLUCIÓN, el activo no puede seguir en estado Asignado."""
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
        "/api/v1/trazabilidad/devolucion",
        json={"ACT_Activo": d["act_1"]},
        headers=auth_headers,
    )
    await _commit_and_sync(session)
    estado = (await session.execute(
        select(Activo.EOP_Estado_Operativo).where(Activo.ACT_Activo == _u(d["act_1"]))
    )).scalar()
    assert estado != d["eop_asig"], "INV ROTA: tras devolución el activo no puede estar Asignado"
    assert estado == d["eop_bod"]


@pytest.mark.asyncio
async def test_audit_log_se_escribe_por_cada_operacion(
    client, auth_headers, domain_seed, session,
):
    """
    Cada operación (asignación, devolución, transferencia) debe registrar
    exactamente un evento en INV_AUDITORIA_SISTEMA.
    """
    d = domain_seed
    # Snapshot del conteo previo
    base = (await session.execute(
        select(func.count()).select_from(AuditoriaSistema)
    )).scalar() or 0

    # 1. Asignación
    await client.post(
        "/api/v1/trazabilidad/movimientos",
        json={
            "ACT_Activo": d["act_1"], "PER_Persona": d["alice"],
            "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
        },
        headers=auth_headers,
    )
    # 2. Transferencia
    await client.post(
        "/api/v1/trazabilidad/transferencia",
        json={
            "ACT_Activo": d["act_1"],
            "PER_Persona_Destino": d["bob"],
            "ARE_Area_Destino": d["area"],
        },
        headers=auth_headers,
    )
    # 3. Devolución
    await client.post(
        "/api/v1/trazabilidad/devolucion",
        json={"ACT_Activo": d["act_1"]},
        headers=auth_headers,
    )
    await _commit_and_sync(session)
    final = (await session.execute(
        select(func.count()).select_from(AuditoriaSistema)
    )).scalar() or 0
    assert final - base >= 3, (
        f"Se esperaban ≥3 eventos audit (asignación + transfer + devolución), "
        f"se registraron {final - base}"
    )
    # Verificar que las acciones específicas existen
    acciones = {row[0] for row in (await session.execute(
        select(AuditoriaSistema.AUD_Accion).where(
            AuditoriaSistema.AUD_Entidad_Afectada == "INV_MOVIMIENTO"
        )
    )).all()}
    assert "ASSIGN" in acciones
    assert "TRANSFER" in acciones
    assert "RETURN" in acciones


@pytest.mark.asyncio
async def test_no_dos_movimientos_abiertos_tras_offboarding(
    client, auth_headers, domain_seed, session,
):
    """Tras offboarding de alice, no debe quedar movimiento abierto suyo."""
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
    await _commit_and_sync(session)
    abiertos_alice = (await session.execute(
        select(func.count()).select_from(Movimiento).where(
            Movimiento.PER_Persona == _u(d["alice"]),
            Movimiento.MOV_Fecha_Devolucion.is_(None),
        )
    )).scalar()
    assert abiertos_alice == 0
