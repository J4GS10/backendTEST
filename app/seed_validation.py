"""
Seed de validacion funcional, seguro para produccion.

Crea un conjunto pequeno e idempotente de registros con prefijo VAL para probar
los flujos principales desde la UI sin usar usuarios con passwords conocidas:

- identidad separada: empleados receptores y usuarios del sistema inactivos/SSO
- catalogos, ubicaciones, activos, especificaciones y codigo automatico
- asignacion vigente, devolucion cerrada y ticket de reparacion abierto
- consumibles con stock bajo e historial de entrada/salida
- compras con orden borrador y orden recibida
- software, licencia e instalaciones en activo/persona
- evento de auditoria que deja trazabilidad de la corrida

Uso:
    docker exec lombardi-backend-1 python -m app.seed_validation
"""
from __future__ import annotations

import asyncio
import json
import logging
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models.catalogs import (
    EstadoOperativo,
    Marca,
    Modelo,
    TipoActivo,
    TipoConexion,
    TipoEspecificacion,
)
from app.models.consumable import Consumible, MovimientoConsumible
from app.models.core import Activo, Especificacion
from app.models.location import Area, Edificio, Estado, Municipio, Nivel, Pais, Sede
from app.models.organization import Cargo, Departamento, Persona, Usuario
from app.models.procurement import OrdenCompra, OrdenCompraLinea, Proveedor
from app.models.procurement import OrdenCompraLineaActivo
from app.models.software import Instalacion, Licencia, LicenciaClave, Software, TipoLicencia
from app.models.traceability import DetalleMantenimiento, Mantenimiento, Movimiento, TipoMantenimiento, TipoMovimiento
from app.repositories.governance import GovernanceRepository
from app.schemas.core import ActivoCreate, EspecificacionCreate
from app.seed_min import seed_min
from app.services.core import CoreService
from app.core.security import encrypt_field, fingerprint_field

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("seed_validation")

SEED_IP = "127.0.0.1"
SEED_AGENT = "app.seed_validation"


async def _one(db: AsyncSession, model, **lookup):
    stmt = select(model)
    for attr, value in lookup.items():
        stmt = stmt.where(getattr(model, attr) == value)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _ensure(db: AsyncSession, model, lookup: dict[str, Any], defaults: dict[str, Any] | None = None):
    obj = await _one(db, model, **lookup)
    created = False
    if obj is None:
        obj = model(**lookup, **(defaults or {}))
        db.add(obj)
        await db.flush()
        created = True
    return obj, created


async def _require_state(db: AsyncSession, name: str) -> EstadoOperativo:
    wanted = _norm(name)
    rows = (await db.execute(select(EstadoOperativo))).scalars().all()
    obj = next((row for row in rows if _norm(row.EOP_Nombre) == wanted), None)
    if obj is None:
        raise RuntimeError(f"Estado operativo requerido no existe: {name}. Ejecuta app.seed_min.")
    return obj


async def _require_movement_type(db: AsyncSession, name: str) -> TipoMovimiento:
    wanted = _norm(name)
    rows = (await db.execute(select(TipoMovimiento))).scalars().all()
    obj = next((row for row in rows if _norm(row.TMO_Nombre) == wanted), None)
    if obj is None:
        raise RuntimeError(f"Tipo de movimiento requerido no existe: {name}. Ejecuta app.seed_min.")
    return obj


async def _require_maintenance_type(db: AsyncSession, name: str) -> TipoMantenimiento:
    wanted = _norm(name)
    rows = (await db.execute(select(TipoMantenimiento))).scalars().all()
    obj = next((row for row in rows if _norm(row.TMA_Nombre) == wanted), None)
    if obj is None:
        raise RuntimeError(f"Tipo de mantenimiento requerido no existe: {name}. Ejecuta app.seed_min.")
    return obj


def _norm(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


async def _operator(db: AsyncSession) -> Usuario | None:
    return (await db.execute(
        select(Usuario)
        .where(Usuario.USU_Rol == "SUPER_ADMIN", Usuario.USU_Estado.is_(True))
        .order_by(Usuario.USU_Username)
        .limit(1)
    )).scalar_one_or_none()


async def _ensure_specs(db: AsyncSession, asset: Activo, specs: dict[str, str]) -> None:
    for name, value in specs.items():
        tipo = (await db.execute(
            select(TipoEspecificacion).where(TipoEspecificacion.TES_Nombre.ilike(name))
        )).scalar_one()
        existing = await _one(
            db,
            Especificacion,
            ACT_Activo=asset.ACT_Activo,
            TES_Tipo_Especificacion=tipo.TES_Tipo_Especificacion,
        )
        if existing is None:
            db.add(Especificacion(
                ACT_Activo=asset.ACT_Activo,
                TES_Tipo_Especificacion=tipo.TES_Tipo_Especificacion,
                ESP_Valor=value,
            ))
        else:
            existing.ESP_Valor = value


async def _ensure_activo(
    db: AsyncSession,
    *,
    code: str,
    serial: str,
    hostname: str | None,
    model_id: int,
    type_id: int,
    state_id: int,
    purchase_date: date,
    warranty_end: date | None,
    cost: Decimal,
) -> Activo:
    asset = await _one(db, Activo, ACT_Codigo_Interno=code)
    if asset is None:
        asset = Activo(
            ACT_Codigo_Interno=code,
            ACT_Serie_Fabricante=serial,
            ACT_Hostname=hostname,
            ACT_Fecha_Compra=purchase_date,
            ACT_Fin_Garantia=warranty_end,
            ACT_Costo=cost,
            MOD_Modelo=model_id,
            TAC_Tipo_Activo=type_id,
            EOP_Estado_Operativo=state_id,
        )
        db.add(asset)
        await db.flush()
    else:
        asset.ACT_Serie_Fabricante = serial
        asset.ACT_Hostname = hostname
        asset.ACT_Fecha_Compra = purchase_date
        asset.ACT_Fin_Garantia = warranty_end
        asset.ACT_Costo = cost
        asset.MOD_Modelo = model_id
        asset.TAC_Tipo_Activo = type_id
        asset.EOP_Estado_Operativo = state_id
    return asset


async def _ensure_closed_movement(
    db: AsyncSession,
    *,
    asset: Activo,
    person: Persona,
    area: Area,
    movement_type: TipoMovimiento,
) -> Movimiento:
    note = "VAL: movimiento cerrado para validar devolucion y acta de descargo"
    mov = (await db.execute(
        select(Movimiento).where(
            Movimiento.ACT_Activo == asset.ACT_Activo,
            Movimiento.MOV_Observacion == note,
        )
    )).scalar_one_or_none()
    assigned_at = datetime.utcnow() - timedelta(days=14)
    returned_at = datetime.utcnow() - timedelta(days=7)
    if mov is None:
        mov = Movimiento(
            ACT_Activo=asset.ACT_Activo,
            PER_Persona=person.PER_Persona,
            ARE_Area=area.ARE_Area,
            TMO_Tipo_Movimiento=movement_type.TMO_Tipo_Movimiento,
            MOV_Fecha_Asignacion=assigned_at,
            MOV_Fecha_Devolucion=returned_at,
            MOV_Observacion=note,
        )
        db.add(mov)
    else:
        mov.MOV_Fecha_Asignacion = assigned_at
        mov.MOV_Fecha_Devolucion = returned_at
    return mov


async def _ensure_open_movement(
    db: AsyncSession,
    *,
    asset: Activo,
    person: Persona,
    area: Area,
    movement_type: TipoMovimiento,
) -> Movimiento:
    existing = (await db.execute(
        select(Movimiento).where(
            Movimiento.ACT_Activo == asset.ACT_Activo,
            Movimiento.MOV_Fecha_Devolucion.is_(None),
        )
    )).scalar_one_or_none()
    if existing:
        existing.PER_Persona = person.PER_Persona
        existing.ARE_Area = area.ARE_Area
        existing.TMO_Tipo_Movimiento = movement_type.TMO_Tipo_Movimiento
        existing.MOV_Observacion = "VAL: asignacion vigente para validar custodia"
        return existing
    mov = Movimiento(
        ACT_Activo=asset.ACT_Activo,
        PER_Persona=person.PER_Persona,
        ARE_Area=area.ARE_Area,
        TMO_Tipo_Movimiento=movement_type.TMO_Tipo_Movimiento,
        MOV_Observacion="VAL: asignacion vigente para validar custodia",
    )
    db.add(mov)
    return mov


async def _ensure_stock_history(db: AsyncSession, consumible: Consumible, person: Persona, user: Usuario | None) -> None:
    consumible.CON_Stock_Actual = 3
    consumible.CON_Stock_Minimo = 5
    entries = [
        ("ENTRADA", 10, 10, "VAL: entrada inicial de validacion", None),
        ("SALIDA", 7, 3, "VAL: salida a empleado para validar bajo stock", person.PER_Persona),
    ]
    for tipo, qty, result, reason, person_id in entries:
        exists = (await db.execute(
            select(MovimientoConsumible).where(
                MovimientoConsumible.CON_Consumible == consumible.CON_Consumible,
                MovimientoConsumible.MOC_Motivo == reason,
            )
        )).scalar_one_or_none()
        if exists is None:
            db.add(MovimientoConsumible(
                CON_Consumible=consumible.CON_Consumible,
                MOC_Tipo=tipo,
                MOC_Cantidad=qty,
                MOC_Stock_Resultante=result,
                MOC_Motivo=reason,
                PER_Persona=person_id,
                USU_Usuario=user.USU_Usuario if user else None,
            ))


async def _line(db: AsyncSession, order: OrdenCompra, description: str, qty: int, price: Decimal, **links):
    existing = (await db.execute(
        select(OrdenCompraLinea).where(
            OrdenCompraLinea.OCO_Orden == order.OCO_Orden,
            OrdenCompraLinea.OCL_Descripcion == description,
        )
    )).scalar_one_or_none()
    subtotal = price * Decimal(qty)
    if existing is None:
        existing = OrdenCompraLinea(
            OCO_Orden=order.OCO_Orden,
            OCL_Descripcion=description,
            OCL_Cantidad=qty,
            OCL_Precio_Unitario=price,
            OCL_Subtotal=subtotal,
            **links,
        )
        db.add(existing)
    else:
        existing.OCL_Cantidad = qty
        existing.OCL_Precio_Unitario = price
        existing.OCL_Subtotal = subtotal
        for key, value in links.items():
            setattr(existing, key, value)
    await db.flush()
    return existing


async def _ensure_line_asset_link(db: AsyncSession, line: OrdenCompraLinea, asset: Activo) -> None:
    existing = await _one(
        db,
        OrdenCompraLineaActivo,
        OCL_Linea=line.OCL_Linea,
        ACT_Activo=asset.ACT_Activo,
    )
    if existing is None:
        db.add(OrdenCompraLineaActivo(
            OCL_Linea=line.OCL_Linea,
            ACT_Activo=asset.ACT_Activo,
        ))


async def _ensure_license_key(db: AsyncSession, license_id: int, key: str, reference: str) -> LicenciaClave:
    key_hash = fingerprint_field(key)
    existing = await _one(db, LicenciaClave, LCL_Clave_Hash=key_hash)
    if existing is None:
        existing = LicenciaClave(
            LIC_Licencia=license_id,
            LCL_Clave_Activacion=encrypt_field(key),
            LCL_Clave_Hash=key_hash,
            LCL_Referencia=reference,
            LCL_Estado="DISPONIBLE",
        )
        db.add(existing)
        await db.flush()
    else:
        existing.LIC_Licencia = license_id
        existing.LCL_Referencia = reference
    return existing


async def seed_validation() -> dict[str, Any]:
    await seed_min()

    today = date.today()
    report: dict[str, Any] = {"prefix": "VAL", "records": {}}

    async with SessionLocal() as db:
        user = await _operator(db)
        user_id = user.USU_Usuario if user else None
        gov = GovernanceRepository(db)

        try:
            disponible = await _require_state(db, "Disponible")
            asignado = await _require_state(db, "Asignado")
            reparacion = await _require_state(db, "En Reparacion")
            bodega = await _require_state(db, "En Bodega")
            tipo_asignacion = await _require_movement_type(db, "Asignacion")
            tma_correctivo = await _require_maintenance_type(db, "Correctivo")

            # Organizacion e identidad.
            dep_rrhh, _ = await _ensure(db, Departamento, {"DEP_Nombre": "VAL-RRHH Validacion"}, {
                "DEP_Codigo_Costos": "VAL-RRHH",
                "DEP_Descripcion": "Departamento de validacion para filtros por contexto.",
            })
            dep_ti, _ = await _ensure(db, Departamento, {"DEP_Nombre": "VAL-TI Validacion"}, {
                "DEP_Codigo_Costos": "VAL-TI",
                "DEP_Descripcion": "Departamento tecnico de validacion.",
            })
            cargo_rrhh, _ = await _ensure(db, Cargo, {"CAR_Nombre": "VAL Analista RRHH"}, {
                "CAR_Es_Jefatura": False,
            })
            cargo_ti, _ = await _ensure(db, Cargo, {"CAR_Nombre": "VAL Tecnico TI"}, {
                "CAR_Es_Jefatura": False,
            })
            cargo_auditor, _ = await _ensure(db, Cargo, {"CAR_Nombre": "VAL Auditor Externo"}, {
                "CAR_Es_Jefatura": False,
            })

            persona_rrhh, _ = await _ensure(db, Persona, {"PER_Email_Corporativo": "val.rrhh@lombardi.validation"}, {
                "PER_Primer_Nombre": "Valeria",
                "PER_Primer_Apellido": "RRHH",
                "PER_Telefono": "5550-0101",
                "DEP_Departamento": dep_rrhh.DEP_Departamento,
                "CAR_Cargo": cargo_rrhh.CAR_Cargo,
            })
            persona_ti, _ = await _ensure(db, Persona, {"PER_Email_Corporativo": "val.ti@lombardi.validation"}, {
                "PER_Primer_Nombre": "Oscar",
                "PER_Primer_Apellido": "TI",
                "PER_Telefono": "5550-0202",
                "DEP_Departamento": dep_ti.DEP_Departamento,
                "CAR_Cargo": cargo_ti.CAR_Cargo,
            })
            persona_aud, _ = await _ensure(db, Persona, {"PER_Email_Corporativo": "val.auditor@lombardi.validation"}, {
                "PER_Primer_Nombre": "Ana",
                "PER_Primer_Apellido": "Auditora",
                "PER_Telefono": "5550-0303",
                "DEP_Departamento": dep_ti.DEP_Departamento,
                "CAR_Cargo": cargo_auditor.CAR_Cargo,
            })

            await _ensure(db, Usuario, {"USU_Username": "val.tecnico.sso"}, {
                "USU_Rol": "TECNICO",
                "USU_Estado": False,
                "USU_SSO_Habilitado": True,
                "USU_SSO_Provider": "microsoft",
                "PER_Persona": persona_ti.PER_Persona,
            })
            await _ensure(db, Usuario, {"USU_Username": "val.auditor.sso"}, {
                "USU_Rol": "CONSULTA",
                "USU_Estado": False,
                "USU_SSO_Habilitado": True,
                "USU_SSO_Provider": "google",
                "PER_Persona": persona_aud.PER_Persona,
            })

            # Ubicacion.
            pais, _ = await _ensure(db, Pais, {"PAI_Nombre": "VAL Pais Validacion"}, {"PAI_Codigo_ISO": "VQ"})
            estado, _ = await _ensure(db, Estado, {"EST_Nombre": "VAL Estado Central", "PAI_Pais": pais.PAI_Pais})
            municipio, _ = await _ensure(db, Municipio, {"MUN_Nombre": "VAL Municipio", "EST_Estado": estado.EST_Estado})
            sede, _ = await _ensure(db, Sede, {"SED_Nombre": "VAL Sede Guatemala", "MUN_Municipio": municipio.MUN_Municipio}, {
                "SED_Direccion_Calle": "Zona validacion",
                "SED_Direccion_Numero": "QA-01",
            })
            edificio, _ = await _ensure(db, Edificio, {"EDI_Nombre": "VAL Edificio Central", "SED_Sede": sede.SED_Sede})
            nivel, _ = await _ensure(db, Nivel, {"NIV_Numero_Piso": "1", "EDI_Edificio": edificio.EDI_Edificio}, {
                "NIV_Alias": "VAL Nivel 1",
            })
            area_rrhh, _ = await _ensure(db, Area, {"ARE_Nombre": "VAL Area RRHH", "NIV_Nivel": nivel.NIV_Nivel}, {
                "ARE_Tipo_Acceso": "General",
                "ARE_Descripcion": "Area de validacion RRHH.",
            })
            area_ti, _ = await _ensure(db, Area, {"ARE_Nombre": "VAL Area TI", "NIV_Nivel": nivel.NIV_Nivel}, {
                "ARE_Tipo_Acceso": "Restringido",
                "ARE_Descripcion": "Area tecnica de validacion.",
            })

            # Catalogos y activos.
            tipo_laptop, _ = await _ensure(db, TipoActivo, {"TAC_Nombre": "VAL Laptop"}, {
                "TAC_Prefijo": "VLT",
                "TAC_Aplica_Depreciacion": True,
            })
            tipo_monitor, _ = await _ensure(db, TipoActivo, {"TAC_Nombre": "VAL Monitor"}, {
                "TAC_Prefijo": "VMN",
                "TAC_Aplica_Depreciacion": True,
            })
            conexion, _ = await _ensure(db, TipoConexion, {"TCN_Nombre": "VAL Integrado"}, {
                "TCN_Descripcion": "Conexion de validacion.",
            })
            marca, _ = await _ensure(db, Marca, {"MAR_Nombre": "VAL Lenovo"})
            modelo_laptop, _ = await _ensure(db, Modelo, {"MOD_Nombre": "VAL ThinkPad E14", "MAR_Marca": marca.MAR_Marca}, {
                "MOD_Anio_Lanzamiento": 2026,
                "TCN_Tipo_Conexion": conexion.TCN_Tipo_Conexion,
                "TAC_Tipo_Activo": tipo_laptop.TAC_Tipo_Activo,
            })
            modelo_monitor, _ = await _ensure(db, Modelo, {"MOD_Nombre": "VAL ThinkVision 24", "MAR_Marca": marca.MAR_Marca}, {
                "MOD_Anio_Lanzamiento": 2026,
                "TCN_Tipo_Conexion": conexion.TCN_Tipo_Conexion,
                "TAC_Tipo_Activo": tipo_monitor.TAC_Tipo_Activo,
            })

            asset_assigned = await _ensure_activo(
                db,
                code="VAL-LAP-001",
                serial="VAL-SN-LAP-001",
                hostname="VAL-RRHH-LAP01",
                model_id=modelo_laptop.MOD_Modelo,
                type_id=tipo_laptop.TAC_Tipo_Activo,
                state_id=asignado.EOP_Estado_Operativo,
                purchase_date=today - timedelta(days=35),
                warranty_end=today + timedelta(days=45),
                cost=Decimal("1250.00"),
            )
            asset_returned = await _ensure_activo(
                db,
                code="VAL-LAP-002",
                serial="VAL-SN-LAP-002",
                hostname="VAL-TI-LAP02",
                model_id=modelo_laptop.MOD_Modelo,
                type_id=tipo_laptop.TAC_Tipo_Activo,
                state_id=bodega.EOP_Estado_Operativo,
                purchase_date=today - timedelta(days=365),
                warranty_end=today - timedelta(days=10),
                cost=Decimal("1180.00"),
            )
            asset_repair = await _ensure_activo(
                db,
                code="VAL-LAP-003",
                serial="VAL-SN-LAP-003",
                hostname="VAL-REPAIR-LAP03",
                model_id=modelo_laptop.MOD_Modelo,
                type_id=tipo_laptop.TAC_Tipo_Activo,
                state_id=reparacion.EOP_Estado_Operativo,
                purchase_date=today - timedelta(days=120),
                warranty_end=today + timedelta(days=250),
                cost=Decimal("1320.00"),
            )
            asset_monitor = await _ensure_activo(
                db,
                code="VAL-MON-001",
                serial="VAL-SN-MON-001",
                hostname=None,
                model_id=modelo_monitor.MOD_Modelo,
                type_id=tipo_monitor.TAC_Tipo_Activo,
                state_id=disponible.EOP_Estado_Operativo,
                purchase_date=today - timedelta(days=20),
                warranty_end=today + timedelta(days=700),
                cost=Decimal("210.00"),
            )
            asset_monitor.ACT_Activo_Padre = asset_assigned.ACT_Activo
            asset_monitor_batch_1 = await _ensure_activo(
                db,
                code="VAL-MON-002",
                serial="VAL-SN-MON-002",
                hostname=None,
                model_id=modelo_monitor.MOD_Modelo,
                type_id=tipo_monitor.TAC_Tipo_Activo,
                state_id=disponible.EOP_Estado_Operativo,
                purchase_date=today - timedelta(days=5),
                warranty_end=today + timedelta(days=720),
                cost=Decimal("215.00"),
            )
            asset_monitor_batch_2 = await _ensure_activo(
                db,
                code="VAL-MON-003",
                serial="VAL-SN-MON-003",
                hostname=None,
                model_id=modelo_monitor.MOD_Modelo,
                type_id=tipo_monitor.TAC_Tipo_Activo,
                state_id=disponible.EOP_Estado_Operativo,
                purchase_date=today - timedelta(days=5),
                warranty_end=today + timedelta(days=720),
                cost=Decimal("215.00"),
            )

            await _ensure_specs(db, asset_assigned, {
                "RAM": "16",
                "Almacenamiento": "512",
                "Procesador": "Intel i7 validacion",
                "Sistema Operativo": "Windows 11 Pro",
            })
            await _ensure_specs(db, asset_repair, {
                "RAM": "8",
                "Almacenamiento": "256",
                "Procesador": "Intel i5 validacion",
            })

            await _ensure_open_movement(
                db,
                asset=asset_assigned,
                person=persona_rrhh,
                area=area_rrhh,
                movement_type=tipo_asignacion,
            )
            await _ensure_closed_movement(
                db,
                asset=asset_returned,
                person=persona_ti,
                area=area_ti,
                movement_type=tipo_asignacion,
            )

            open_ticket = (await db.execute(
                select(Mantenimiento).where(
                    Mantenimiento.ACT_Activo == asset_repair.ACT_Activo,
                    Mantenimiento.MAN_Fecha_Cierre.is_(None),
                )
            )).scalar_one_or_none()
            if open_ticket is None:
                open_ticket = Mantenimiento(
                    ACT_Activo=asset_repair.ACT_Activo,
                    PER_Persona_Solicita=persona_ti.PER_Persona,
                    TMA_Tipo_Mantenimiento=tma_correctivo.TMA_Tipo_Mantenimiento,
                    MAN_Descripcion_Falla="VAL: ticket abierto para validar reparacion.",
                    MAN_Costo_Total=Decimal("0.00"),
                )
                db.add(open_ticket)
                await db.flush()
            detail = (await db.execute(
                select(DetalleMantenimiento).where(
                    DetalleMantenimiento.MAN_Mantenimiento == open_ticket.MAN_Mantenimiento,
                    DetalleMantenimiento.DMA_Accion_Realizada == "VAL: diagnostico inicial",
                )
            )).scalar_one_or_none()
            if detail is None:
                db.add(DetalleMantenimiento(
                    MAN_Mantenimiento=open_ticket.MAN_Mantenimiento,
                    DMA_Accion_Realizada="VAL: diagnostico inicial",
                    DMA_Costo_Item=Decimal("25.00"),
                ))

            # Consumibles.
            consumible, _ = await _ensure(db, Consumible, {"CON_Nombre": "VAL Toner HP 85A"}, {
                "CON_Descripcion": "Consumible de validacion con stock bajo.",
                "CON_Categoria": "Toner",
                "CON_Unidad": "unidad",
                "CON_Stock_Actual": 3,
                "CON_Stock_Minimo": 5,
            })
            await _ensure_stock_history(db, consumible, persona_rrhh, user)

            # Compras.
            proveedor, _ = await _ensure(db, Proveedor, {"PRV_Nombre": "VAL Proveedor Tecnologia"}, {
                "PRV_Identificacion_Fiscal": "VAL-NIT-001",
                "PRV_Contacto": "Mesa Validacion",
                "PRV_Email": "proveedor.val@lombardi.validation",
                "PRV_Telefono": "5550-0404",
                "PRV_Direccion": "Direccion de validacion",
            })
            orden_draft, _ = await _ensure(db, OrdenCompra, {"OCO_Numero": "VAL-OC-BORRADOR-0001"}, {
                "OCO_Fecha": today,
                "OCO_Estado": "BORRADOR",
                "OCO_Moneda": "GTQ",
                "OCO_Total": Decimal("0.00"),
                "OCO_Notas": "VAL: orden borrador para validar recepcion.",
                "PRV_Proveedor": proveedor.PRV_Proveedor,
                "USU_Usuario": user_id,
            })
            await _line(db, orden_draft, "VAL Laptop pendiente de recepcion", 1, Decimal("1190.00"))
            orden_draft.OCO_Moneda = "GTQ"
            orden_draft.OCO_Total = Decimal("1190.00")

            orden_rec, _ = await _ensure(db, OrdenCompra, {"OCO_Numero": "VAL-OC-RECIBIDA-0001"}, {
                "OCO_Fecha": today - timedelta(days=7),
                "OCO_Estado": "RECIBIDA",
                "OCO_Moneda": "GTQ",
                "OCO_Total": Decimal("0.00"),
                "OCO_Notas": "VAL: orden recibida para validar garantias y compras.",
                "PRV_Proveedor": proveedor.PRV_Proveedor,
                "USU_Usuario": user_id,
            })
            orden_rec.OCO_Estado = "RECIBIDA"
            orden_rec.OCO_Moneda = "GTQ"
            await _line(
                db,
                orden_rec,
                "VAL Laptop recibida y vinculada",
                1,
                Decimal("1180.00"),
                ACT_Activo=asset_returned.ACT_Activo,
            )
            await _line(
                db,
                orden_rec,
                "VAL Toner reabastecido y vinculado",
                10,
                Decimal("18.00"),
                CON_Consumible=consumible.CON_Consumible,
            )
            orden_rec.OCO_Total = Decimal("1360.00")

            orden_lote, _ = await _ensure(db, OrdenCompra, {"OCO_Numero": "VAL-OC-LOTE-CHF-0001"}, {
                "OCO_Fecha": today - timedelta(days=5),
                "OCO_Estado": "RECIBIDA",
                "OCO_Moneda": "CHF",
                "OCO_Total": Decimal("0.00"),
                "OCO_Notas": "VAL: orden recibida con multiples activos serializados en una linea.",
                "PRV_Proveedor": proveedor.PRV_Proveedor,
                "USU_Usuario": user_id,
            })
            orden_lote.OCO_Estado = "RECIBIDA"
            orden_lote.OCO_Moneda = "CHF"
            line_lote = await _line(
                db,
                orden_lote,
                "VAL lote de monitores con series individuales",
                2,
                Decimal("215.00"),
                ACT_Activo=asset_monitor_batch_1.ACT_Activo,
            )
            await _ensure_line_asset_link(db, line_lote, asset_monitor_batch_1)
            await _ensure_line_asset_link(db, line_lote, asset_monitor_batch_2)
            orden_lote.OCO_Total = Decimal("430.00")

            # Software y licencias.
            tipo_lic, _ = await _ensure(db, TipoLicencia, {"TLI_Nombre": "VAL Suscripcion"}, {
                "TLI_Descripcion": "Tipo de licencia de validacion.",
            })
            software, _ = await _ensure(db, Software, {
                "SOF_Nombre": "VAL Suite Productividad",
                "SOF_Version": "2026",
                "SOF_Fabricante": "VAL Software",
            })
            licencia, _ = await _ensure(db, Licencia, {"SOF_Software": software.SOF_Software, "TLI_Tipo_Licencia": tipo_lic.TLI_Tipo_Licencia}, {
                "LIC_Clave_Activacion": None,
                "LIC_Fecha_Vencimiento": today + timedelta(days=365),
                "LIC_Cantidad_Total": 5,
                "LIC_Cantidad_Usada": 0,
            })
            licencia.LIC_Cantidad_Total = 5
            licencia_keys = []
            for index in range(1, 6):
                licencia_keys.append(await _ensure_license_key(
                    db,
                    licencia.LIC_Licencia,
                    f"VAL-SUITE-2026-{index:03d}",
                    f"VAL licencia individual {index}",
                ))
            for target in (
                {"ACT_Activo": asset_assigned.ACT_Activo, "PER_Persona": None},
                {"ACT_Activo": None, "PER_Persona": persona_aud.PER_Persona},
            ):
                stmt = select(Instalacion).where(
                    Instalacion.LIC_Licencia == licencia.LIC_Licencia,
                    Instalacion.INS_Estado.is_(True),
                )
                if target["ACT_Activo"]:
                    stmt = stmt.where(Instalacion.ACT_Activo == target["ACT_Activo"])
                else:
                    stmt = stmt.where(Instalacion.PER_Persona == target["PER_Persona"])
                install = (await db.execute(stmt)).scalar_one_or_none()
                if install is None:
                    db.add(Instalacion(
                        LIC_Licencia=licencia.LIC_Licencia,
                        ACT_Activo=target["ACT_Activo"],
                        PER_Persona=target["PER_Persona"],
                        INS_Fecha_Instalacion=today,
                        INS_Estado=True,
                    ))
            await db.flush()
            active_installations = (await db.execute(
                select(Instalacion).where(
                    Instalacion.LIC_Licencia == licencia.LIC_Licencia,
                    Instalacion.INS_Estado.is_(True),
                ).order_by(Instalacion.INS_Instalacion)
            )).scalars().all()
            assigned_key_ids = set()
            for install, key in zip(active_installations, licencia_keys):
                install.LCL_Licencia_Clave = key.LCL_Licencia_Clave
                key.LCL_Estado = "ASIGNADA"
                assigned_key_ids.add(key.LCL_Licencia_Clave)
            for key in licencia_keys:
                if key.LCL_Licencia_Clave not in assigned_key_ids:
                    key.LCL_Estado = "DISPONIBLE"
            active_count = (await db.execute(
                select(func.count()).select_from(Instalacion).where(
                    Instalacion.LIC_Licencia == licencia.LIC_Licencia,
                    Instalacion.INS_Estado.is_(True),
                )
            )).scalar_one()
            licencia.LIC_Cantidad_Usada = int(active_count)
            line_license = await _line(
                db,
                orden_rec,
                "VAL Suite Productividad 5 claves individuales",
                5,
                Decimal("12.00"),
                LIC_Licencia=licencia.LIC_Licencia,
            )
            orden_rec.OCO_Total = Decimal("1420.00")

            await gov.create_audit_log(
                "VALIDATION_SEED",
                "SYS_VALIDATION",
                {
                    "version": "2026-07-03",
                    "scope": [
                        "identity",
                        "assets",
                        "traceability",
                        "maintenance",
                        "consumables",
                        "procurement",
                        "software",
                        "audit",
                    ],
                    "records": {
                        "assets": [
                            "VAL-LAP-001",
                            "VAL-LAP-002",
                            "VAL-LAP-003",
                            "VAL-MON-001",
                            "VAL-MON-002",
                            "VAL-MON-003",
                        ],
                        "people": [
                            "val.rrhh@lombardi.validation",
                            "val.ti@lombardi.validation",
                            "val.auditor@lombardi.validation",
                        ],
                        "orders": ["VAL-OC-BORRADOR-0001", "VAL-OC-RECIBIDA-0001", "VAL-OC-LOTE-CHF-0001"],
                        "consumable": "VAL Toner HP 85A",
                        "software": "VAL Suite Productividad",
                    },
                },
                usuario_id=user_id,
                ip_origen=SEED_IP,
                user_agent=SEED_AGENT,
            )
            await db.commit()

            # Activo con codigo automatico: se crea por servicio para validar
            # la secuencia transaccional race-safe. Se hace despues del commit
            # base porque CoreService gestiona su propia transaccion.
            auto_asset = await _one(db, Activo, ACT_Serie_Fabricante="VAL-SN-AUTO-001")
            if auto_asset is None:
                ram = (await db.execute(
                    select(TipoEspecificacion).where(TipoEspecificacion.TES_Nombre.ilike("RAM"))
                )).scalar_one()
                auto_asset = await CoreService(db).create_activo(
                    ActivoCreate(
                        ACT_Codigo_Interno=None,
                        ACT_Serie_Fabricante="VAL-SN-AUTO-001",
                        ACT_Hostname="VAL-AUTO-CODE",
                        ACT_Fecha_Compra=today,
                        ACT_Fin_Garantia=today + timedelta(days=365),
                        ACT_Costo=Decimal("999.00"),
                        MOD_Modelo=modelo_laptop.MOD_Modelo,
                        TAC_Tipo_Activo=tipo_laptop.TAC_Tipo_Activo,
                        EOP_Estado_Operativo=disponible.EOP_Estado_Operativo,
                        ACT_Activo_Padre=None,
                        especificaciones=[
                            EspecificacionCreate(
                                TES_Tipo_Especificacion=ram.TES_Tipo_Especificacion,
                                ESP_Valor="16",
                            )
                        ],
                    ),
                    usuario_id=user_id,
                )

            report["records"] = {
                "personas": {
                    "rrhh": str(persona_rrhh.PER_Persona),
                    "ti": str(persona_ti.PER_Persona),
                    "auditor": str(persona_aud.PER_Persona),
                },
                "usuarios_sistema_inactivos_sso": ["val.tecnico.sso", "val.auditor.sso"],
                "areas": ["VAL Area RRHH", "VAL Area TI"],
                "activos": [
                    {"codigo": "VAL-LAP-001", "estado": "Asignado", "uso": "custodia vigente y garantia por vencer"},
                    {"codigo": "VAL-LAP-002", "estado": "En Bodega", "uso": "movimiento cerrado y garantia vencida"},
                    {"codigo": "VAL-LAP-003", "estado": "En Reparacion", "uso": "ticket abierto"},
                    {"codigo": "VAL-MON-001", "estado": "Disponible", "uso": "componente hijo"},
                    {"codigo": "VAL-MON-002", "estado": "Disponible", "uso": "lote de compra CHF"},
                    {"codigo": "VAL-MON-003", "estado": "Disponible", "uso": "lote de compra CHF"},
                    {"codigo": auto_asset.ACT_Codigo_Interno, "estado": "Disponible", "uso": "codigo automatico"},
                ],
                "consumibles": [{"nombre": "VAL Toner HP 85A", "stock": 3, "minimo": 5}],
                "compras": ["VAL-OC-BORRADOR-0001", "VAL-OC-RECIBIDA-0001", "VAL-OC-LOTE-CHF-0001"],
                "software": {
                    "nombre": "VAL Suite Productividad",
                    "licencias_total": licencia.LIC_Cantidad_Total,
                    "licencias_usadas": licencia.LIC_Cantidad_Usada,
                    "claves_individuales": len(licencia_keys),
                    "claves_disponibles": len(licencia_keys) - licencia.LIC_Cantidad_Usada,
                },
                "auditoria": "Evento VALIDATION_SEED en INV_AUDITORIA_SISTEMA",
            }
        except Exception:
            await db.rollback()
            raise

    return report


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


if __name__ == "__main__":
    result = asyncio.run(seed_validation())
    log.info("Seed de validacion completado.")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=_json_default))
