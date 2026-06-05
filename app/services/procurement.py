"""Servicio de Compras: Proveedores, Órdenes de Compra y vista de Garantías."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import internal_error
from app.models.consumable import MovimientoConsumible
from app.models.procurement import OrdenCompra, OrdenCompraLinea
from app.repositories.catalogs import CatalogRepository
from app.repositories.consumable import ConsumibleRepository
from app.repositories.core import CoreRepository
from app.repositories.governance import GovernanceRepository
from app.repositories.procurement import ProcurementRepository
from app.schemas.core import ActivoCreate
from app.schemas.procurement import (
    OrdenCreate, ProveedorCreate, ProveedorUpdate, RecepcionOrden,
)


class ProcurementService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ProcurementRepository(db)
        self.gov_repo = GovernanceRepository(db)

    # =====================================================================
    # PROVEEDOR
    # =====================================================================
    async def list_proveedores(self, solo_activos: bool = False):
        return await self.repo.get_proveedores(solo_activos=solo_activos)

    async def get_proveedor(self, id: int):
        obj = await self.repo.get_proveedor(id)
        if not obj:
            raise HTTPException(404, "SUPPLIER_NOT_FOUND")
        return obj

    async def create_proveedor(self, schema: ProveedorCreate, usuario_id=None, ip=None):
        try:
            if await self.repo.get_proveedor_by_name(schema.PRV_Nombre):
                raise HTTPException(409, "SUPPLIER_ALREADY_EXISTS")
            obj = await self.repo.create_proveedor(schema)
            await self.gov_repo.create_audit_log(
                "CREATE", "INV_PROVEEDOR", {"nombre": schema.PRV_Nombre},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            await self.db.refresh(obj)
            return obj
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def update_proveedor(self, id: int, schema: ProveedorUpdate, usuario_id=None, ip=None):
        try:
            if not await self.repo.get_proveedor(id):
                raise HTTPException(404, "SUPPLIER_NOT_FOUND")
            obj = await self.repo.update_proveedor(id, schema)
            await self.gov_repo.create_audit_log(
                "UPDATE", "INV_PROVEEDOR",
                {"id": id, "cambios": schema.model_dump(exclude_unset=True, mode="json")},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            return obj
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def delete_proveedor(self, id: int, usuario_id=None, ip=None):
        try:
            prov = await self.repo.get_proveedor(id)
            if not prov:
                raise HTTPException(404, "SUPPLIER_NOT_FOUND")
            if await self.repo.count_ordenes_de_proveedor(id) > 0:
                raise HTTPException(409, "CANNOT_DELETE_SUPPLIER_HAS_ORDERS")
            await self.repo.delete_proveedor(id)
            await self.gov_repo.create_audit_log(
                "DELETE", "INV_PROVEEDOR", {"id": id, "nombre": prov.PRV_Nombre},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    # =====================================================================
    # ORDEN DE COMPRA
    # =====================================================================
    async def list_ordenes(self, estado: str | None = None):
        return await self.repo.list_ordenes(estado=estado)

    async def get_orden(self, id: int):
        obj = await self.repo.get_orden(id, with_lineas=True)
        if not obj:
            raise HTTPException(404, "PURCHASE_ORDER_NOT_FOUND")
        return obj

    async def create_orden(self, schema: OrdenCreate, usuario_id=None, ip=None):
        try:
            if not await self.repo.get_proveedor(schema.PRV_Proveedor):
                raise HTTPException(404, "SUPPLIER_NOT_FOUND")
            if await self.repo.get_orden_by_numero(schema.OCO_Numero):
                raise HTTPException(409, "PURCHASE_ORDER_NUMBER_EXISTS")

            orden = OrdenCompra(
                OCO_Numero=schema.OCO_Numero,
                OCO_Fecha=schema.OCO_Fecha,
                OCO_Moneda=schema.OCO_Moneda,
                OCO_Notas=schema.OCO_Notas,
                PRV_Proveedor=schema.PRV_Proveedor,
                USU_Usuario=usuario_id,
                OCO_Estado="BORRADOR",
            )
            total = Decimal("0")
            for ln in schema.lineas:
                subtotal = (Decimal(ln.OCL_Precio_Unitario) * ln.OCL_Cantidad).quantize(Decimal("0.01"))
                total += subtotal
                orden.lineas.append(OrdenCompraLinea(
                    OCL_Descripcion=ln.OCL_Descripcion,
                    OCL_Cantidad=ln.OCL_Cantidad,
                    OCL_Precio_Unitario=Decimal(ln.OCL_Precio_Unitario),
                    OCL_Subtotal=subtotal,
                    ACT_Activo=ln.ACT_Activo,
                    CON_Consumible=ln.CON_Consumible,
                ))
            orden.OCO_Total = total

            await self.repo.add_orden(orden)
            await self.gov_repo.create_audit_log(
                "CREATE", "INV_ORDEN_COMPRA",
                {"numero": schema.OCO_Numero, "proveedor_id": schema.PRV_Proveedor,
                 "total": str(total), "lineas": len(schema.lineas)},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            return await self.repo.get_orden(orden.OCO_Orden, with_lineas=True)
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def cambiar_estado(self, id: int, estado: str, usuario_id=None, ip=None):
        try:
            orden = await self.repo.get_orden(id, with_lineas=False)
            if not orden:
                raise HTTPException(404, "PURCHASE_ORDER_NOT_FOUND")
            if orden.OCO_Estado == "CANCELADA":
                raise HTTPException(409, "ORDER_ALREADY_CANCELLED")
            await self.repo.set_estado_orden(id, estado)
            await self.gov_repo.create_audit_log(
                "UPDATE", "INV_ORDEN_COMPRA",
                {"id": id, "diff": {"OCO_Estado": {"antes": orden.OCO_Estado, "despues": estado}}},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            return await self.repo.get_orden(id, with_lineas=True)
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    # =====================================================================
    # RECEPCIÓN — lazo cerrado: suma stock de consumibles + da de alta activos
    # =====================================================================
    async def recibir_orden(self, id: int, schema: RecepcionOrden, usuario_id=None, ip=None):
        try:
            orden = await self.repo.get_orden(id, with_lineas=True)
            if not orden:
                raise HTTPException(404, "PURCHASE_ORDER_NOT_FOUND")
            if orden.OCO_Estado != "BORRADOR":
                raise HTTPException(409, "ORDER_NOT_RECEIVABLE")  # ya recibida o cancelada

            lineas_validas = {ln.OCL_Linea: ln for ln in orden.lineas}

            con_repo = ConsumibleRepository(self.db)
            core_repo = CoreRepository(self.db)
            cat_repo = CatalogRepository(self.db)

            # --- 1. Consumibles: sumar stock (entrada auditada) ---
            reabastecidos = 0
            for rc in schema.consumibles:
                if rc.OCL_Linea not in lineas_validas:
                    raise HTTPException(400, "LINE_NOT_IN_ORDER")
                con = await con_repo.get_by_id(rc.CON_Consumible)
                if not con:
                    raise HTTPException(404, "CONSUMABLE_NOT_FOUND")
                await con_repo.incrementar_stock(rc.CON_Consumible, rc.cantidad)
                refreshed = await con_repo.get_by_id(rc.CON_Consumible)
                await con_repo.add_movimiento(MovimientoConsumible(
                    CON_Consumible=rc.CON_Consumible, MOC_Tipo="ENTRADA",
                    MOC_Cantidad=rc.cantidad, MOC_Stock_Resultante=refreshed.CON_Stock_Actual,
                    MOC_Motivo=f"Recepción OC {orden.OCO_Numero}", USU_Usuario=usuario_id,
                ))
                # Enlazar la línea al consumible si no lo estaba.
                lineas_validas[rc.OCL_Linea].CON_Consumible = rc.CON_Consumible
                await self.gov_repo.create_audit_log(
                    "STOCK_IN", "INV_CONSUMIBLE",
                    {"id": rc.CON_Consumible, "cantidad": rc.cantidad,
                     "stock_resultante": refreshed.CON_Stock_Actual,
                     "motivo": f"Recepción OC {orden.OCO_Numero}"},
                    usuario_id=usuario_id, ip_origen=ip,
                )
                reabastecidos += 1

            # --- 2. Activos: alta + enlace a la línea (estado Disponible) ---
            from app.models.catalogs import EstadoOperativo
            from sqlalchemy import select as _select
            estado_disp = (await self.db.execute(
                _select(EstadoOperativo).where(EstadoOperativo.EOP_Nombre.ilike("Disponible"))
            )).scalar_one_or_none()
            if schema.activos and not estado_disp:
                # Fail-closed: sin el estado canónico, no corrompemos el alta.
                raise HTTPException(500, "SYSTEM_CONFIGURATION_ERROR_MISSING_STATUS_DISPONIBLE")

            codigos_creados: list[str] = []
            for ra in schema.activos:
                if ra.OCL_Linea not in lineas_validas:
                    raise HTTPException(400, "LINE_NOT_IN_ORDER")
                tipo = await cat_repo.get_tipo_activo_by_id(ra.TAC_Tipo_Activo)
                if not tipo:
                    raise HTTPException(404, "ASSET_TYPE_NOT_FOUND")
                if not await cat_repo.get_modelo_by_id(ra.MOD_Modelo):
                    raise HTTPException(404, "MODEL_NOT_FOUND")

                codigo = ra.ACT_Codigo_Interno
                if not codigo:
                    if not tipo.TAC_Prefijo:
                        raise HTTPException(400, "ASSET_TYPE_HAS_NO_PREFIX_CONFIGURED_FOR_AUTO_GENERATION")
                    codigo = await self.gov_repo.get_next_code(
                        contexto=f"ASSET_{tipo.TAC_Prefijo}", prefijo=tipo.TAC_Prefijo)
                if await core_repo.get_by_codigo_interno(codigo):
                    raise HTTPException(400, "ASSET_CODE_ALREADY_EXISTS")
                if await core_repo.get_by_serie(ra.ACT_Serie_Fabricante):
                    raise HTTPException(400, "SERIAL_NUMBER_ALREADY_EXISTS")
                if ra.ACT_Fin_Garantia and ra.ACT_Fin_Garantia < ra.ACT_Fecha_Compra:
                    raise HTTPException(400, "WARRANTY_DATE_CANNOT_BE_BEFORE_PURCHASE_DATE")

                nuevo = await core_repo.create_activo(ActivoCreate(
                    ACT_Codigo_Interno=codigo,
                    ACT_Serie_Fabricante=ra.ACT_Serie_Fabricante,
                    ACT_Hostname=ra.ACT_Hostname,
                    ACT_Fecha_Compra=ra.ACT_Fecha_Compra,
                    ACT_Fin_Garantia=ra.ACT_Fin_Garantia,
                    ACT_Costo=ra.ACT_Costo,
                    MOD_Modelo=ra.MOD_Modelo,
                    TAC_Tipo_Activo=ra.TAC_Tipo_Activo,
                    EOP_Estado_Operativo=estado_disp.EOP_Estado_Operativo,
                ))
                # Enlazar la línea al activo recién creado (alimenta garantías↔proveedor).
                lineas_validas[ra.OCL_Linea].ACT_Activo = nuevo.ACT_Activo
                await self.gov_repo.create_audit_log(
                    "CREATE", "INV_ACTIVO",
                    {"codigo": codigo, "serie": ra.ACT_Serie_Fabricante,
                     "origen": f"Recepción OC {orden.OCO_Numero}"},
                    usuario_id=usuario_id, ip_origen=ip,
                )
                codigos_creados.append(codigo)

            # --- 3. Marcar la orden como recibida ---
            await self.repo.set_estado_orden(id, "RECIBIDA")
            await self.gov_repo.create_audit_log(
                "UPDATE", "INV_ORDEN_COMPRA",
                {"id": id, "diff": {"OCO_Estado": {"antes": "BORRADOR", "despues": "RECIBIDA"}},
                 "consumibles_reabastecidos": reabastecidos, "activos_creados": len(codigos_creados)},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            return {
                "OCO_Orden": id, "OCO_Estado": "RECIBIDA",
                "consumibles_reabastecidos": reabastecidos,
                "activos_creados": len(codigos_creados),
                "activos_codigos": codigos_creados,
            }
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    # =====================================================================
    # GARANTÍAS
    # =====================================================================
    async def garantias(self, dias: int = 90, solo_alertas: bool = False):
        """
        Lista activos con su estado de garantía. `dias` define la ventana
        "por vencer". `solo_alertas` filtra a por_vencer + vencida.
        """
        rows = await self.repo.garantias()
        hoy = date.today()
        umbral = hoy + timedelta(days=dias)

        vistos: set = set()
        items = []
        for r in rows:
            act_id = r[0]
            if act_id in vistos:
                continue
            vistos.add(act_id)
            fin = r[4]
            if fin is None:
                estado, dias_rest = "sin_garantia", None
            elif fin < hoy:
                estado, dias_rest = "vencida", (fin - hoy).days
            elif fin <= umbral:
                estado, dias_rest = "por_vencer", (fin - hoy).days
            else:
                estado, dias_rest = "vigente", (fin - hoy).days

            if solo_alertas and estado not in ("por_vencer", "vencida"):
                continue

            items.append({
                "ACT_Activo": act_id,
                "ACT_Codigo_Interno": r[1],
                "ACT_Serie_Fabricante": r[2],
                "ACT_Fecha_Compra": r[3],
                "ACT_Fin_Garantia": fin,
                "dias_restantes": dias_rest,
                "estado_garantia": estado,
                "proveedor": r[5],
            })

        # Orden: alertas primero (vencida, por_vencer), luego vigente, luego sin.
        prioridad = {"vencida": 0, "por_vencer": 1, "vigente": 2, "sin_garantia": 3}
        items.sort(key=lambda x: (prioridad[x["estado_garantia"]],
                                  x["dias_restantes"] if x["dias_restantes"] is not None else 10**9))
        return items

    async def notificar_garantias(self, dias: int = 90):
        """
        Envía a los admins un digest de garantías vencidas/por vencer. Pensado
        para dispararse periódicamente (cron/routine) o a demanda. Devuelve el
        conteo; el email es fire-and-forget (no bloquea si SMTP falla).
        """
        alertas = await self.garantias(dias=dias, solo_alertas=True)
        if not alertas:
            return {"total": 0, "enviado": False}
        from app.core.email import send_notification
        items = [
            {"codigo": a["ACT_Codigo_Interno"],
             "fin": a["ACT_Fin_Garantia"].isoformat() if a["ACT_Fin_Garantia"] else "—",
             "estado": "Vencida" if a["estado_garantia"] == "vencida" else "Por vencer",
             "dias": a["dias_restantes"]}
            for a in alertas
        ]
        await send_notification(
            "garantia_por_vencer",
            {"total": len(alertas), "dias": dias, "items": items},
            to=(),  # solo admins
        )
        return {"total": len(alertas), "enviado": True}
