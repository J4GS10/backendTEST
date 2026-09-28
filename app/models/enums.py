from enum import Enum


class EstadoOperativoEnum(str, Enum):
    DISPONIBLE = "Disponible"
    BODEGA = "En Bodega"
    ASIGNADO = "Asignado"
    REPARACION = "En Reparación"
    BAJA = "Baja"
    TRANSITO = "En Tránsito"


class TipoMovimientoEnum(str, Enum):
    INGRESO = "Ingreso"
    ASIGNACION = "Asignación"
    DEVOLUCION = "Devolución"
    TRANSFERENCIA = "Transferencia"
    PRESTAMO = "Préstamo"
    BAJA = "Baja por Retiro"
