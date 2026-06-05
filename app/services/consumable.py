"""Servicio de Consumibles (inventario por cantidad)."""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import internal_error
from app.models.consumable import MovimientoConsumible
from app.repositories.consumable import ConsumibleRepository
from app.repositories.governance import GovernanceRepository
from app.schemas.consumable import (
    ConsumibleCreate, ConsumibleUpdate, StockMovimientoCreate,
)


def _con_to_response(con) -> dict:
    """Serializa un Consumible añadiendo el flag calculado bajo_stock."""
    return {
        "CON_Consumible": con.CON_Consumible,
        "CON_Nombre": con.CON_Nombre,
        "CON_Descripcion": con.CON_Descripcion,
        "CON_Categoria": con.CON_Categoria,
        "CON_Unidad": con.CON_Unidad,
        "CON_Stock_Actual": con.CON_Stock_Actual,
        "CON_Stock_Minimo": con.CON_Stock_Minimo,
        "CON_Activo": con.CON_Activo,
        "bajo_stock": con.CON_Stock_Minimo > 0 and con.CON_Stock_Actual <= con.CON_Stock_Minimo,
    }


class ConsumableService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ConsumibleRepository(db)
        self.gov_repo = GovernanceRepository(db)

    async def list(self, solo_bajo_stock: bool = False):
        items = await self.repo.get_all(solo_bajo_stock=solo_bajo_stock)
        return [_con_to_response(c) for c in items]

    async def get(self, id: int):
        obj = await self.repo.get_by_id(id)
        if not obj:
            raise HTTPException(404, "CONSUMABLE_NOT_FOUND")
        return _con_to_response(obj)

    async def create(self, schema: ConsumibleCreate, usuario_id=None, ip=None):
        try:
            if await self.repo.get_by_name(schema.CON_Nombre):
                raise HTTPException(409, "CONSUMABLE_ALREADY_EXISTS")
            obj = await self.repo.create(schema)
            await self.gov_repo.create_audit_log(
                "CREATE", "INV_CONSUMIBLE",
                {"nombre": schema.CON_Nombre, "stock_inicial": schema.CON_Stock_Actual},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            await self.db.refresh(obj)
            return _con_to_response(obj)
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def update(self, id: int, schema: ConsumibleUpdate, usuario_id=None, ip=None):
        try:
            obj = await self.repo.get_by_id(id)
            if not obj:
                raise HTTPException(404, "CONSUMABLE_NOT_FOUND")
            updated = await self.repo.update(id, schema)
            await self.gov_repo.create_audit_log(
                "UPDATE", "INV_CONSUMIBLE",
                {"id": id, "cambios": schema.model_dump(exclude_unset=True)},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            return _con_to_response(updated)
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def delete(self, id: int, usuario_id=None, ip=None):
        try:
            obj = await self.repo.get_by_id(id)
            if not obj:
                raise HTTPException(404, "CONSUMABLE_NOT_FOUND")
            # Si tiene historial de movimientos, no se borra (preserva trazabilidad).
            if await self.repo.count_movimientos(id) > 0:
                raise HTTPException(409, "CANNOT_DELETE_CONSUMABLE_HAS_MOVEMENTS")
            await self.repo.delete(id)
            await self.gov_repo.create_audit_log(
                "DELETE", "INV_CONSUMIBLE",
                {"id": id, "nombre": obj.CON_Nombre},
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    # ------------------------------------------------------------------
    # Stock
    # ------------------------------------------------------------------
    async def registrar_entrada(
        self, id: int, schema: StockMovimientoCreate,
        usuario_id: uuid.UUID | None = None, ip=None,
    ):
        return await self._mover_stock(id, schema, "ENTRADA", usuario_id, ip)

    async def registrar_salida(
        self, id: int, schema: StockMovimientoCreate,
        usuario_id: uuid.UUID | None = None, ip=None,
    ):
        return await self._mover_stock(id, schema, "SALIDA", usuario_id, ip)

    async def _mover_stock(self, id: int, schema, tipo: str, usuario_id, ip):
        try:
            obj = await self.repo.get_by_id(id)
            if not obj:
                raise HTTPException(404, "CONSUMABLE_NOT_FOUND")

            # Capturar metadatos ANTES del UPDATE (que sincroniza el objeto en sesión).
            stock_antes = obj.CON_Stock_Actual
            nombre, minimo, unidad, categoria = (
                obj.CON_Nombre, obj.CON_Stock_Minimo, obj.CON_Unidad, obj.CON_Categoria,
            )

            if tipo == "ENTRADA":
                ok = await self.repo.incrementar_stock(id, schema.MOC_Cantidad)
            else:  # SALIDA — atómico, falla si no hay stock suficiente
                ok = await self.repo.decrementar_stock(id, schema.MOC_Cantidad)
                if not ok:
                    raise HTTPException(409, "INSUFFICIENT_STOCK")
            if not ok:
                raise HTTPException(409, "STOCK_OPERATION_FAILED")

            # Releer el stock resultante para el snapshot del movimiento.
            refreshed = await self.repo.get_by_id(id)
            stock_despues = refreshed.CON_Stock_Actual
            mov = MovimientoConsumible(
                CON_Consumible=id,
                MOC_Tipo=tipo,
                MOC_Cantidad=schema.MOC_Cantidad,
                MOC_Stock_Resultante=stock_despues,
                MOC_Motivo=schema.MOC_Motivo,
                PER_Persona=schema.PER_Persona,
                USU_Usuario=usuario_id,
            )
            await self.repo.add_movimiento(mov)

            await self.gov_repo.create_audit_log(
                "STOCK_IN" if tipo == "ENTRADA" else "STOCK_OUT", "INV_CONSUMIBLE",
                {
                    "id": id, "nombre": nombre, "cantidad": schema.MOC_Cantidad,
                    "stock_resultante": stock_despues, "motivo": schema.MOC_Motivo,
                },
                usuario_id=usuario_id, ip_origen=ip,
            )
            await self.db.commit()
            await self.db.refresh(mov)

            # Alerta de stock bajo: solo al CRUZAR el umbral (evita spam si ya estaba bajo).
            cruzo = minimo > 0 and stock_antes > minimo and stock_despues <= minimo
            if cruzo:
                await self._notificar_stock_bajo(
                    nombre, stock_despues, minimo, unidad, categoria, usuario_id,
                )
            return mov
        except HTTPException:
            await self.db.rollback(); raise
        except Exception as e:
            await self.db.rollback()
            raise internal_error(e, "TRANSACTION_FAILED")

    async def _notificar_stock_bajo(self, nombre, stock_actual, minimo, unidad, categoria, usuario_id):
        """Email post-commit fire-and-forget a admins. No bloquea ni revierte."""
        try:
            from sqlalchemy import select as _select
            from app.core.email import send_notification
            from app.models.organization import Persona, Usuario

            op_name, op_role, op_email = "Sistema", "", None
            if usuario_id:
                usu = (await self.db.execute(
                    _select(Usuario).where(Usuario.USU_Usuario == usuario_id)
                )).scalar_one_or_none()
                if usu:
                    op_role = usu.USU_Rol or ""
                    per = (await self.db.execute(
                        _select(Persona).where(Persona.PER_Persona == usu.PER_Persona)
                    )).scalar_one_or_none()
                    if per:
                        op_name = f"{per.PER_Primer_Nombre} {per.PER_Primer_Apellido}"
                        op_email = per.PER_Email_Corporativo
            await send_notification(
                "stock_bajo",
                {"codigo": nombre, "stock_actual": stock_actual, "stock_minimo": minimo,
                 "unidad": unidad, "categoria": categoria or ""},
                to=(),  # solo admins
                reply_to=op_email, operator_name=op_name, operator_role=op_role,
            )
        except Exception:  # noqa: BLE001
            pass

    async def list_movimientos(self, id: int):
        obj = await self.repo.get_by_id(id)
        if not obj:
            raise HTTPException(404, "CONSUMABLE_NOT_FOUND")
        return await self.repo.get_movimientos(id)
