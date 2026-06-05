"""Repositorio de Compras (Proveedores + Órdenes). Sin commits internos."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.models.procurement import OrdenCompra, OrdenCompraLinea, Proveedor
from app.schemas.procurement import ProveedorCreate, ProveedorUpdate


class ProcurementRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------------- PROVEEDOR ----------------
    async def create_proveedor(self, schema: ProveedorCreate) -> Proveedor:
        data = schema.model_dump()
        if data.get("PRV_Email") is not None:
            data["PRV_Email"] = str(data["PRV_Email"])
        obj = Proveedor(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_proveedores(self, solo_activos: bool = False) -> List[Proveedor]:
        query = select(Proveedor).order_by(Proveedor.PRV_Nombre)
        if solo_activos:
            query = query.where(Proveedor.PRV_Activo.is_(True))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_proveedor(self, id: int) -> Optional[Proveedor]:
        result = await self.db.execute(
            select(Proveedor).where(Proveedor.PRV_Proveedor == id)
        )
        return result.scalar_one_or_none()

    async def get_proveedor_by_name(self, nombre: str) -> Optional[Proveedor]:
        result = await self.db.execute(
            select(Proveedor).where(Proveedor.PRV_Nombre == nombre)
        )
        return result.scalar_one_or_none()

    async def update_proveedor(self, id: int, schema: ProveedorUpdate) -> Optional[Proveedor]:
        data = schema.model_dump(exclude_unset=True)
        if data.get("PRV_Email") is not None:
            data["PRV_Email"] = str(data["PRV_Email"])
        if data:
            await self.db.execute(
                update(Proveedor).where(Proveedor.PRV_Proveedor == id).values(**data)
            )
            await self.db.flush()
        return await self.get_proveedor(id)

    async def delete_proveedor(self, id: int) -> None:
        await self.db.execute(delete(Proveedor).where(Proveedor.PRV_Proveedor == id))
        await self.db.flush()

    async def count_ordenes_de_proveedor(self, id: int) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(OrdenCompra).where(OrdenCompra.PRV_Proveedor == id)
        )
        return result.scalar_one()

    # ---------------- ORDEN ----------------
    async def get_orden_by_numero(self, numero: str) -> Optional[OrdenCompra]:
        result = await self.db.execute(
            select(OrdenCompra).where(OrdenCompra.OCO_Numero == numero)
        )
        return result.scalar_one_or_none()

    async def add_orden(self, orden: OrdenCompra) -> OrdenCompra:
        self.db.add(orden)
        await self.db.flush()
        return orden

    async def get_orden(self, id: int, with_lineas: bool = True) -> Optional[OrdenCompra]:
        query = select(OrdenCompra).where(OrdenCompra.OCO_Orden == id).options(
            selectinload(OrdenCompra.proveedor)
        )
        if with_lineas:
            query = query.options(selectinload(OrdenCompra.lineas))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_ordenes(self, estado: Optional[str] = None) -> List[OrdenCompra]:
        query = (
            select(OrdenCompra)
            .options(selectinload(OrdenCompra.proveedor))
            .order_by(OrdenCompra.OCO_Fecha.desc(), OrdenCompra.OCO_Orden.desc())
        )
        if estado:
            query = query.where(OrdenCompra.OCO_Estado == estado)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def set_estado_orden(self, id: int, estado: str) -> None:
        await self.db.execute(
            update(OrdenCompra).where(OrdenCompra.OCO_Orden == id).values(OCO_Estado=estado)
        )
        await self.db.flush()

    # ---------------- GARANTÍAS ----------------
    async def garantias(self):
        """
        Devuelve cada activo con su fin de garantía y, si existe, el proveedor
        derivado de la línea de orden que lo referencia (LEFT JOIN no invasivo).
        """
        from app.models.core import Activo

        # Subconsulta: proveedor por activo vía línea de orden (una cualquiera).
        result = await self.db.execute(
            select(
                Activo.ACT_Activo,
                Activo.ACT_Codigo_Interno,
                Activo.ACT_Serie_Fabricante,
                Activo.ACT_Fecha_Compra,
                Activo.ACT_Fin_Garantia,
                Proveedor.PRV_Nombre,
            )
            .outerjoin(OrdenCompraLinea, OrdenCompraLinea.ACT_Activo == Activo.ACT_Activo)
            .outerjoin(OrdenCompra, OrdenCompra.OCO_Orden == OrdenCompraLinea.OCO_Orden)
            .outerjoin(Proveedor, Proveedor.PRV_Proveedor == OrdenCompra.PRV_Proveedor)
            .order_by(Activo.ACT_Codigo_Interno)
        )
        return result.all()
