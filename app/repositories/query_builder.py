"""
Query builder fluido para búsquedas con filtros dinámicos.

Encapsula la construcción de SELECT con WHERE opcionales, ORDER BY y paginación.
Evita condicionales `if filter:` dispersos en los repositorios.

Patrón aplicado: Builder (fluent interface).

Uso:

    stmt, total = await (
        AsyncQueryBuilder(db, Activo)
        .filter(Activo.EOP_Estado_Operativo == estado_id, when=estado_id is not None)
        .ilike(Activo.ACT_Codigo_Interno, q, when=bool(q))
        .ilike(Activo.ACT_Serie_Fabricante, q, when=bool(q), or_group=True)
        .order_by(Activo.ACT_Codigo_Interno)
        .paginate(page=1, per_page=25)
        .build()
    )
"""
from __future__ import annotations

from typing import Any, Optional, Sequence, Tuple, Type, TypeVar

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

M = TypeVar("M")


class AsyncQueryBuilder(object):
    """Builder asíncrono para consultas SELECT con filtros opcionales."""

    def __init__(self, db: AsyncSession, model: Type[M]) -> None:
        self._db = db
        self._model = model
        self._conditions: list[Any] = []
        self._or_groups: list[list[Any]] = []
        self._current_or: list[Any] = []
        self._order: list[Any] = []
        self._page: int = 1
        self._per_page: Optional[int] = None
        self._eager: list[Any] = []

    # ── Filtros ─────────────────────────────────────────────────────────────

    def filter(self, condition: Any, *, when: bool = True) -> "AsyncQueryBuilder":
        """Agrega un WHERE exacto si `when` es True."""
        if when:
            self._conditions.append(condition)
        return self

    def ilike(
        self,
        column: InstrumentedAttribute,
        value: str,
        *,
        when: bool = True,
        or_group: bool = False,
    ) -> "AsyncQueryBuilder":
        """
        Búsqueda de texto insensible a mayúsculas.
        or_group=True acumula el filtro en un OR con el anterior ilike.
        """
        if not when:
            return self
        expr = column.ilike(f"%{value}%")
        if or_group:
            self._current_or.append(expr)
        else:
            if self._current_or:
                self._conditions.append(or_(*self._current_or))
                self._current_or = []
            self._current_or = [expr]
        return self

    def eager(self, *options: Any) -> "AsyncQueryBuilder":
        """Agrega opciones de carga eager (selectinload / joinedload)."""
        self._eager.extend(options)
        return self

    def order_by(self, *columns: Any) -> "AsyncQueryBuilder":
        self._order.extend(columns)
        return self

    def paginate(self, *, page: int = 1, per_page: int = 25) -> "AsyncQueryBuilder":
        self._page = max(1, page)
        self._per_page = max(1, per_page)
        return self

    # ── Build ───────────────────────────────────────────────────────────────

    async def build(self) -> Tuple[Sequence[M], int]:
        """
        Ejecuta la query. Retorna (items, total).
        Si no se llamó paginate(), retorna todos los registros (total == len(items)).
        """
        # Cierra grupos OR abiertos
        if self._current_or:
            self._conditions.append(or_(*self._current_or))
            self._current_or = []

        # COUNT
        count_stmt = select(func.count()).select_from(self._model)
        if self._conditions:
            count_stmt = count_stmt.where(*self._conditions)
        total: int = (await self._db.execute(count_stmt)).scalar_one()

        # DATA
        data_stmt = select(self._model)
        for opt in self._eager:
            data_stmt = data_stmt.options(opt)
        if self._conditions:
            data_stmt = data_stmt.where(*self._conditions)
        if self._order:
            data_stmt = data_stmt.order_by(*self._order)
        if self._per_page is not None:
            offset = (self._page - 1) * self._per_page
            data_stmt = data_stmt.offset(offset).limit(self._per_page)

        items = (await self._db.execute(data_stmt)).scalars().all()
        return items, total
