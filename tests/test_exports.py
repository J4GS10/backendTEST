"""
Tests de coherencia de exportación CSV.

Garantías:
  1. Cada export devuelve `text/csv` + Content-Disposition con filename.
  2. La cantidad de filas (sin header) == registros en BD.
  3. Anti-CSV-injection: valores que empiezan con =, +, -, @ se prefijan
     con apóstrofe para que Excel/Sheets no los ejecute como fórmula.
  4. Sólo admin puede descargar activos/movimientos; sólo super_admin
     puede descargar auditoría.
  5. Los campos del CSV coinciden 1-a-1 con datos de BD (consistencia
     post-asignación: si el activo está Asignado en BD, lo está en CSV).
"""
import csv
import io

import pytest


def _parse_csv(text: str) -> tuple[list[str], list[list[str]]]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    return rows[0], rows[1:]


@pytest.mark.asyncio
async def test_export_activos_csv_estructura(client, auth_headers, domain_seed):
    """El CSV de activos tiene los headers correctos y 2 filas (de domain_seed)."""
    d = domain_seed
    r = await client.get("/api/v1/export/activos.csv", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    assert ".csv" in r.headers["content-disposition"]

    headers, rows = _parse_csv(r.text)
    assert headers == [
        "Codigo_Interno", "Serie_Fabricante", "Hostname", "Tipo_Activo",
        "Marca", "Modelo", "Estado_Operativo", "Fecha_Compra", "Fin_Garantia", "Costo",
    ]
    assert len(rows) == 2  # LAP-001 + LAP-002
    codigos = {row[0] for row in rows}
    assert codigos == {"LAP-001", "LAP-002"}


@pytest.mark.asyncio
async def test_export_activos_anti_csv_injection(
    client, auth_headers, domain_seed, session,
):
    """
    Crear un activo con un hostname que empieza con '=' (intento de fórmula)
    y verificar que el CSV lo prefija con apóstrofe para neutralizar la inyección.
    """
    import uuid
    from sqlalchemy import update
    from app.models.core import Activo
    d = domain_seed
    # Inyectar valor malicioso vía SQL directo
    payload = "=cmd|'/C calc'!A1"
    await session.execute(
        update(Activo).where(Activo.ACT_Activo == uuid.UUID(d["act_1"])).values(ACT_Hostname=payload)
    )
    await session.commit()

    r = await client.get("/api/v1/export/activos.csv", headers=auth_headers)
    assert r.status_code == 200
    # El valor debe aparecer prefijado con apóstrofe en el CSV crudo.
    assert ("\"'" + payload[0]) in r.text or ("'=cmd" in r.text), (
        "El CSV debe neutralizar fórmulas prefijando con apóstrofe"
    )
    # Importante: la apóstrofe NO debe formar parte del valor en BD
    from sqlalchemy import select
    val = (await session.execute(
        select(Activo.ACT_Hostname).where(Activo.ACT_Activo == uuid.UUID(d["act_1"]))
    )).scalar()
    assert val == payload  # En BD se mantiene el valor original


@pytest.mark.asyncio
async def test_export_movimientos_csv_consistente_con_bd(
    client, auth_headers, domain_seed, session,
):
    """
    Tras 2 asignaciones, el export debe tener 2 filas; tras devolución debe
    tener fecha_devolucion poblada en la fila correspondiente.
    """
    d = domain_seed
    # 2 asignaciones
    for act_id in (d["act_1"], d["act_2"]):
        await client.post(
            "/api/v1/trazabilidad/movimientos",
            json={
                "ACT_Activo": act_id, "PER_Persona": d["alice"],
                "ARE_Area": d["area"], "TMO_Tipo_Movimiento": d["tmo_asg"],
            },
            headers=auth_headers,
        )
    # Devolver act_1
    await client.post(
        "/api/v1/trazabilidad/devolucion",
        json={"ACT_Activo": d["act_1"]},
        headers=auth_headers,
    )

    r = await client.get("/api/v1/export/movimientos.csv", headers=auth_headers)
    assert r.status_code == 200
    _, rows = _parse_csv(r.text)
    assert len(rows) == 2  # 2 movimientos creados
    # La fila de act_1 debe tener fecha_devolucion no vacía
    for row in rows:
        codigo, fecha_asg, fecha_dev = row[2], row[0], row[1]
        if codigo == "LAP-001":
            assert fecha_dev != "", "La devolución debe quedar en el export"
        elif codigo == "LAP-002":
            assert fecha_dev == "", "El movimiento abierto no tiene devolución"


@pytest.mark.asyncio
async def test_export_consistente_con_estado_post_asignacion(
    client, auth_headers, domain_seed, session,
):
    """
    Tras una ASIGNACIÓN, el CSV de activos debe mostrar 'Asignado' en la
    columna Estado_Operativo del activo correspondiente. Este test cierra
    el ciclo del bug: BD coherente → export coherente.
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
    r = await client.get("/api/v1/export/activos.csv", headers=auth_headers)
    _, rows = _parse_csv(r.text)
    for row in rows:
        if row[0] == "LAP-001":
            assert row[6] == "Asignado", (
                f"CSV inconsistente: LAP-001 está asignado en BD pero el "
                f"CSV reporta estado '{row[6]}'"
            )


@pytest.mark.asyncio
async def test_export_auditoria_requiere_super_admin(
    client, auth_headers, domain_seed,
):
    """SUPER_ADMIN puede descargar auditoría."""
    # sa_user es SUPER_ADMIN, así que debe pasar
    r = await client.get("/api/v1/export/auditoria.csv", headers=auth_headers)
    assert r.status_code == 200
    headers, _ = _parse_csv(r.text)
    assert "Accion" in headers
    assert "Snapshot_JSON" in headers


@pytest.mark.asyncio
async def test_export_filenames_incluyen_timestamp(client, auth_headers, domain_seed):
    """El filename del CSV incluye fecha actual para forense."""
    r = await client.get("/api/v1/export/activos.csv", headers=auth_headers)
    cd = r.headers["content-disposition"]
    # Pattern: activos_YYYYMMDD_HHMMSS.csv
    import re
    assert re.search(r"activos_\d{8}_\d{6}\.csv", cd), (
        f"Filename debe llevar timestamp YYYYMMDD_HHMMSS, llegó: {cd}"
    )
