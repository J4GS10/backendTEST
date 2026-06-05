"""
Seed MÍNIMO canónico (seguro en producción, idempotente).

Inserta SOLO los datos de catálogo de los que depende la LÓGICA del sistema, sin
ninguna data de demostración (no crea usuarios, personas, activos ni movimientos):

- EstadoOperativo: Disponible, Asignado, En Reparación, Baja, En Bodega.
  REQUERIDOS por las transiciones de estado (asignación, devolución, transferencia,
  recepción de orden, baja). Sin ellos esos flujos fallan (fail-closed).
- TipoMovimiento: Ingreso, Asignación, Devolución, Préstamo, Transferencia.
  REQUERIDOS por registrar_movimiento / transferencia (que buscan por nombre).
- TipoMantenimiento: Preventivo, Correctivo, Predictivo (para poder abrir tickets).
- TipoEspecificacion: RAM, Almacenamiento, Procesador, etc. (características de activos).
- TipoEvidencia: Fotografía, Acta firmada, Reporte técnico.

Idempotente fila a fila (inserta por nombre solo si falta), así que se puede correr en
cada arranque sin duplicar. A diferencia de seed_demo, NO aborta en producción.

Uso:
    docker exec lombardi-backend-1 python -m app.seed_min
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.catalogs import EstadoOperativo, TipoEspecificacion
from app.models.traceability import TipoEvidencia, TipoMantenimiento, TipoMovimiento

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("seed_min")


# (modelo, atributo-nombre-único, lista de kwargs por fila)
_CANONICAL = [
    (EstadoOperativo, "EOP_Nombre", [
        {"EOP_Nombre": "Disponible", "EOP_Descripcion": "Listo para asignación"},
        {"EOP_Nombre": "Asignado", "EOP_Descripcion": "En uso por una persona"},
        {"EOP_Nombre": "En Reparación", "EOP_Descripcion": "Mantenimiento abierto"},
        {"EOP_Nombre": "Baja", "EOP_Descripcion": "Fuera de inventario"},
        {"EOP_Nombre": "En Bodega", "EOP_Descripcion": "Almacenado sin asignar"},
    ]),
    (TipoMovimiento, "TMO_Nombre", [
        {"TMO_Nombre": "Ingreso"},
        {"TMO_Nombre": "Asignación"},
        {"TMO_Nombre": "Devolución"},
        {"TMO_Nombre": "Préstamo"},
        {"TMO_Nombre": "Transferencia"},
    ]),
    (TipoMantenimiento, "TMA_Nombre", [
        {"TMA_Nombre": "Preventivo"},
        {"TMA_Nombre": "Correctivo"},
        {"TMA_Nombre": "Predictivo"},
    ]),
    (TipoEspecificacion, "TES_Nombre", [
        {"TES_Nombre": "RAM", "TES_Unidad_Medida": "GB"},
        {"TES_Nombre": "Almacenamiento", "TES_Unidad_Medida": "GB"},
        {"TES_Nombre": "Procesador"},
        {"TES_Nombre": "Tarjeta Gráfica"},
        {"TES_Nombre": "Sistema Operativo"},
        {"TES_Nombre": "Tamaño Pantalla", "TES_Unidad_Medida": "pulgadas"},
    ]),
    (TipoEvidencia, "TEV_Nombre", [
        {"TEV_Nombre": "Fotografía"},
        {"TEV_Nombre": "Acta firmada"},
        {"TEV_Nombre": "Reporte técnico"},
    ]),
]


async def seed_min() -> None:
    total_creados = 0
    async with SessionLocal() as db:
        for model, name_attr, rows in _CANONICAL:
            col = getattr(model, name_attr)
            existentes = set(
                (await db.execute(select(col))).scalars().all()
            )
            nuevos = 0
            for row in rows:
                if row[name_attr] not in existentes:
                    db.add(model(**row))
                    nuevos += 1
            if nuevos:
                await db.flush()
            total_creados += nuevos
            log.info("%-20s: %d nuevos (%d ya existían)", model.__name__, nuevos, len(existentes))
        await db.commit()
    log.info("Seed mínimo completado. Filas creadas: %d", total_creados)


if __name__ == "__main__":
    asyncio.run(seed_min())
