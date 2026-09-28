"""
Alcance de datos por sede (RLS).

Cada petición autenticada fija el alcance del usuario (`DataScope`): global o
un conjunto de sedes. El alcance se aplica en DOS capas independientes:

1. Aplicación (todos los motores): un listener `do_orm_execute` añade
   `with_loader_criteria` a toda consulta ORM (SELECT, UPDATE y DELETE),
   incluidas las cargas de relaciones. Un repositorio que olvide filtrar
   igualmente solo ve filas del alcance.
2. PostgreSQL: al comenzar cada transacción de una petición se ejecuta
   `SET LOCAL ROLE <DB_RLS_ROLE>` y `set_config('app.usuario', …)`. Ese rol no
   es dueño de las tablas, así que las políticas de `app/db/rls.py` se aplican
   aunque el backend se conecte como superusuario.

Qué define la visibilidad:
- INV_ACTIVO, INV_PERSONA, INV_ORDEN_COMPRA e INV_CONSUMIBLE tienen sede propia.
- Movimientos, mantenimientos, especificaciones, instalaciones, adjuntos y
  evidencias heredan la visibilidad del activo (u orden) al que pertenecen.
- Una persona también es visible si está vinculada a un registro visible
  (custodia, mantenimiento, instalación o consumo), para que el historial de
  un activo muestre a sus custodios, y siempre lo es la persona del propio usuario.
- La bitácora: registros de las sedes del alcance y las acciones propias.

Fuera de una petición (tareas periódicas, cola de correos, migraciones,
scripts) no hay alcance: modo sistema, sin filtros. `system_scope()` permite
entrar explícitamente en ese modo (p. ej. en los hooks post-commit).
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import AsyncIterator, Iterator

import structlog
from fastapi import HTTPException
from sqlalchemy import and_, event, or_, select, text
from sqlalchemy.orm import Session, with_loader_criteria

from app.core import roles
from app.core.config import settings

log = structlog.get_logger("data_scope")


@dataclass(frozen=True)
class DataScope:
    usuario_id: uuid.UUID
    persona_id: uuid.UUID | None
    rol: str
    is_global: bool
    sedes: frozenset[int]

    @property
    def restricted(self) -> bool:
        return not self.is_global

    def allows(self, sede_id: int | None) -> bool:
        if self.is_global:
            return True
        return sede_id is not None and sede_id in self.sedes


_current: ContextVar[DataScope | None] = ContextVar("data_scope", default=None)


def user_is_global(user) -> bool:
    """Alcance global efectivo de una cuenta (los roles de gobierno siempre lo son)."""
    return user.USU_Rol in roles.ALWAYS_GLOBAL_ROLES or bool(getattr(user, "USU_Alcance_Global", False))


def scope_for_user(user) -> DataScope:
    return DataScope(
        usuario_id=user.USU_Usuario,
        persona_id=user.PER_Persona,
        rol=user.USU_Rol,
        is_global=user_is_global(user),
        sedes=frozenset(s.SED_Sede for s in (user.sedes or [])),
    )


def current_scope() -> DataScope | None:
    """Alcance de la petición en curso; None = modo sistema (sin filtros)."""
    return _current.get()


def set_request_scope(scope: DataScope | None) -> None:
    _current.set(scope)


@contextmanager
def system_scope() -> Iterator[None]:
    """Ejecuta un bloque sin alcance (tareas internas del sistema)."""
    token = _current.set(None)
    try:
        yield
    finally:
        _current.reset(token)


@contextmanager
def user_scope(scope: DataScope | None) -> Iterator[None]:
    """Ejecuta un bloque con un alcance concreto (tests y tareas delegadas)."""
    token = _current.set(scope)
    try:
        yield
    finally:
        _current.reset(token)


# ---------------------------------------------------------------------------
# Validaciones de escritura (la lectura la filtran los criterios automáticos)
# ---------------------------------------------------------------------------
def visible_sede_ids() -> list[int] | None:
    """Sedes del alcance; None = todas (global o sistema)."""
    scope = current_scope()
    if scope is None or scope.is_global:
        return None
    return sorted(scope.sedes)


def strict_sede_clause(column):
    """
    Filtro estricto por sede para listados (p. ej. el padrón de personas: solo
    las de sus sedes, no las visibles por historial). None = sin filtro.
    """
    ids = visible_sede_ids()
    return None if ids is None else column.in_(ids)


def require_owned(sede_id: int | None) -> None:
    """Modificar un registro existente exige que su sede esté en el alcance."""
    scope = current_scope()
    if scope is not None and not scope.allows(sede_id):
        raise HTTPException(403, "SEDE_OUT_OF_SCOPE")


@asynccontextmanager
async def elevated(session) -> AsyncIterator[None]:
    """
    Comprobación del sistema dentro de una petición de usuario, sin alcance:
    unicidad global (código, serie, correo) o completitud (¿quedan
    asignaciones en sedes que el usuario no ve?). Solo para LEER y decidir; lo
    leído no se devuelve al usuario. En PostgreSQL se sale del rol restringido
    durante el bloque y se vuelve a entrar al terminar.
    """
    scope = current_scope()
    db_layer = (
        scope is not None
        and session.in_transaction()
        and _db_layer_active(session.get_bind().dialect.name)
        and session.sync_session.info.get(_INFO_KEY) == scope.usuario_id
    )
    with system_scope():
        if db_layer:
            await session.execute(text("RESET ROLE"))
        try:
            yield
        finally:
            if db_layer:
                try:
                    await session.execute(text(f'SET LOCAL ROLE "{settings.DB_RLS_ROLE}"'))
                except Exception:  # noqa: BLE001
                    # Transacción abortada: el rollback que sigue descarta el
                    # SET LOCAL y nada más puede ejecutarse en ella.
                    log.warning("data_scope.elevated_restore_failed")
                    raise


async def area_sede_id(session, area_id: int) -> int | None:
    """Sede de un área (Área → Nivel → Edificio → Sede)."""
    from app.models.location import Area, Edificio, Nivel
    return (await session.execute(
        select(Edificio.SED_Sede)
        .join(Nivel, Nivel.EDI_Edificio == Edificio.EDI_Edificio)
        .join(Area, Area.NIV_Nivel == Nivel.NIV_Nivel)
        .where(Area.ARE_Area == area_id)
    )).scalar_one_or_none()


def default_sede_id() -> int | None:
    """Sede implícita: la única del alcance, si el usuario tiene exactamente una."""
    ids = visible_sede_ids()
    return ids[0] if ids and len(ids) == 1 else None


def require_sede(sede_id: int | None, *, required: bool = True) -> int | None:
    """
    Valida la sede de un registro nuevo o modificado y la devuelve.

    - Sin sede: se usa la única del alcance si el usuario tiene exactamente una;
      si no, 400 SEDE_REQUIRED (salvo `required=False` para usuarios globales).
    - Sede fuera del alcance: 403 SEDE_OUT_OF_SCOPE.
    En modo sistema (sin petición) no se valida.
    """
    scope = current_scope()
    if scope is None:
        return sede_id
    if sede_id is None:
        sede_id = default_sede_id()
    if sede_id is None:
        if scope.restricted or required:
            raise HTTPException(400, "SEDE_REQUIRED")
        return None
    if not scope.allows(sede_id):
        raise HTTPException(403, "SEDE_OUT_OF_SCOPE")
    return sede_id


# ---------------------------------------------------------------------------
# Capa 1: criterios ORM automáticos
# ---------------------------------------------------------------------------
def _scope_options(scope: DataScope) -> list:
    from app.models.attachment import Adjunto
    from app.models.consumable import Consumible, MovimientoConsumible
    from app.models.core import Activo, Especificacion
    from app.models.governance import AuditoriaSistema
    from app.models.organization import Persona
    from app.models.procurement import OrdenCompra, OrdenCompraLinea, OrdenCompraLineaActivo
    from app.models.software import Instalacion
    from app.models.traceability import DetalleMantenimiento, Evidencia, Mantenimiento, Movimiento

    sedes = tuple(sorted(scope.sedes))
    persona_t = Persona.__table__
    activos = select(Activo.ACT_Activo).where(Activo.SED_Sede.in_(sedes))
    ordenes = select(OrdenCompra.OCO_Orden).where(OrdenCompra.SED_Sede.in_(sedes))
    consumibles = select(Consumible.CON_Consumible).where(Consumible.SED_Sede.in_(sedes))
    mantenimientos = select(Mantenimiento.MAN_Mantenimiento).where(Mantenimiento.ACT_Activo.in_(activos))
    movimientos = select(Movimiento.MOV_Movimiento).where(Movimiento.ACT_Activo.in_(activos))
    lineas = select(OrdenCompraLinea.OCL_Linea).where(OrdenCompraLinea.OCO_Orden.in_(ordenes))

    persona_rules = [
        Persona.SED_Sede.in_(sedes),
        Persona.PER_Persona.in_(select(Movimiento.PER_Persona).where(Movimiento.ACT_Activo.in_(activos))),
        Persona.PER_Persona.in_(
            select(Mantenimiento.PER_Persona_Solicita).where(Mantenimiento.ACT_Activo.in_(activos))
        ),
        Persona.PER_Persona.in_(select(Instalacion.PER_Persona).where(Instalacion.ACT_Activo.in_(activos))),
        Persona.PER_Persona.in_(
            select(MovimientoConsumible.PER_Persona).where(MovimientoConsumible.CON_Consumible.in_(consumibles))
        ),
    ]
    if scope.persona_id is not None:
        persona_rules.append(Persona.PER_Persona == scope.persona_id)

    criteria = {
        Activo: Activo.SED_Sede.in_(sedes),
        Especificacion: Especificacion.ACT_Activo.in_(activos),
        Movimiento: Movimiento.ACT_Activo.in_(activos),
        Mantenimiento: Mantenimiento.ACT_Activo.in_(activos),
        DetalleMantenimiento: DetalleMantenimiento.MAN_Mantenimiento.in_(mantenimientos),
        Evidencia: or_(
            Evidencia.MOV_Movimiento_Ref.in_(movimientos),
            Evidencia.MAN_Mantenimiento_Ref.in_(mantenimientos),
        ),
        # A un activo visible o, sin activo, a una persona de las sedes del alcance
        # (tabla Core: sin criterios ORM anidados que formen un ciclo).
        Instalacion: or_(
            Instalacion.ACT_Activo.in_(activos),
            and_(
                Instalacion.ACT_Activo.is_(None),
                Instalacion.PER_Persona.in_(
                    select(persona_t.c.PER_Persona).where(persona_t.c.SED_Sede.in_(sedes))
                ),
            ),
        ),
        Adjunto: or_(Adjunto.ACT_Activo.in_(activos), Adjunto.OCO_Orden.in_(ordenes)),
        OrdenCompra: OrdenCompra.SED_Sede.in_(sedes),
        OrdenCompraLinea: OrdenCompraLinea.OCO_Orden.in_(ordenes),
        OrdenCompraLineaActivo: OrdenCompraLineaActivo.OCL_Linea.in_(lineas),
        Consumible: Consumible.SED_Sede.in_(sedes),
        MovimientoConsumible: MovimientoConsumible.CON_Consumible.in_(consumibles),
        Persona: or_(*persona_rules),
        AuditoriaSistema: or_(
            AuditoriaSistema.AUD_Sede.in_(sedes),
            AuditoriaSistema.USU_Usuario == scope.usuario_id,
        ),
    }
    return [
        with_loader_criteria(entity, clause, include_aliases=True)
        for entity, clause in criteria.items()
    ]


@event.listens_for(Session, "do_orm_execute")
def _apply_scope(state) -> None:
    scope = current_scope()
    if scope is None:
        return
    _ensure_db_scope(state.session, scope)
    if scope.is_global:
        return
    if state.is_column_load or state.is_relationship_load:
        # Los criterios ya se propagan a las cargas de relaciones.
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if state.execution_options.get("skip_data_scope"):
        return
    state.statement = state.statement.options(*_scope_options(scope))


# ---------------------------------------------------------------------------
# Capa 2: RLS de PostgreSQL
# ---------------------------------------------------------------------------
_RLS_STATE: dict[str, bool | None] = {"available": None}
_INFO_KEY = "data_scope_applied"


def set_db_rls_available(value: bool) -> None:
    """Resultado de la verificación de arranque (rol creado y concedido)."""
    _RLS_STATE["available"] = value


def db_rls_available() -> bool | None:
    return _RLS_STATE["available"]


def _db_layer_active(dialect_name: str) -> bool:
    return (
        settings.DB_RLS_ENABLED
        and _RLS_STATE["available"] is True
        and dialect_name == "postgresql"
    )


def _set_db_scope(connection, scope: DataScope) -> None:
    connection.execute(
        text("SELECT set_config('app.usuario', :usuario, true)"),
        {"usuario": str(scope.usuario_id)},
    )
    connection.execute(text(f'SET LOCAL ROLE "{settings.DB_RLS_ROLE}"'))


def _ensure_db_scope(session: Session, scope: DataScope) -> None:
    """
    Aplica el rol y el usuario a la transacción en curso si aún no se hizo:
    cubre la transacción que ya estaba abierta cuando la autenticación fijó
    el alcance. Las transacciones siguientes las cubre `after_begin`.
    """
    if session.get_transaction() is None:
        return
    if session.info.get(_INFO_KEY) == scope.usuario_id:
        return
    if not _db_layer_active(session.get_bind().dialect.name):
        return
    connection = session.connection()  # puede disparar after_begin, que ya lo aplica
    if session.info.get(_INFO_KEY) == scope.usuario_id:
        return
    _set_db_scope(connection, scope)
    session.info[_INFO_KEY] = scope.usuario_id


@event.listens_for(Session, "after_begin")
def _scope_new_transaction(session, transaction, connection) -> None:
    scope = current_scope()
    if scope is None or not _db_layer_active(connection.dialect.name):
        return
    _set_db_scope(connection, scope)
    session.info[_INFO_KEY] = scope.usuario_id


@event.listens_for(Session, "after_transaction_end")
def _clear_db_scope_marker(session, transaction) -> None:
    # SET LOCAL muere con la transacción raíz: la próxima debe volver a aplicarse.
    if transaction.parent is None:
        session.info.pop(_INFO_KEY, None)
