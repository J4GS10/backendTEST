"""Motor de estados para el ciclo de vida de los activos."""
from typing import Dict, Set
from app.models.enums import EstadoOperativoEnum
from app.core.errors import InvalidStateTransitionError

class AssetStateMachine:
    """
    Define las transiciones permitidas entre estados operativos.
    Proporciona validación centralizada para evitar inconsistencias.
    """

    # Matriz de transiciones legales: { EstadoOrigen: {EstadosDestinoPermitidos} }
    TRANSITIONS: Dict[EstadoOperativoEnum, Set[EstadoOperativoEnum]] = {
        EstadoOperativoEnum.DISPONIBLE: {
            EstadoOperativoEnum.ASIGNADO,     # Asignación/Préstamo
            EstadoOperativoEnum.BODEGA,       # Movimiento interno
            EstadoOperativoEnum.REPARACION,   # Envío a taller
            EstadoOperativoEnum.BAJA,         # Retiro
            EstadoOperativoEnum.TRANSITO,     # Envío entre sedes
        },
        EstadoOperativoEnum.BODEGA: {
            EstadoOperativoEnum.ASIGNADO,
            EstadoOperativoEnum.DISPONIBLE,
            EstadoOperativoEnum.REPARACION,
            EstadoOperativoEnum.BAJA,
            EstadoOperativoEnum.TRANSITO,
        },
        EstadoOperativoEnum.ASIGNADO: {
            EstadoOperativoEnum.BODEGA,       # Devolución (obligatorio pasar por bodega/disponible antes de re-asignar o reparar)
            EstadoOperativoEnum.DISPONIBLE,
            EstadoOperativoEnum.ASIGNADO,     # Transferencia directa entre personas
            EstadoOperativoEnum.TRANSITO,
        },
        EstadoOperativoEnum.REPARACION: {
            EstadoOperativoEnum.BODEGA,       # Retorno de taller
            EstadoOperativoEnum.DISPONIBLE,
            EstadoOperativoEnum.BAJA,         # Si no tiene reparación
        },
        EstadoOperativoEnum.TRANSITO: {
            EstadoOperativoEnum.BODEGA,       # Llegada a destino
            EstadoOperativoEnum.DISPONIBLE,
        },
        EstadoOperativoEnum.BAJA: {
            # Se permite reversar la baja (por error humano) regresando a un estado de almacén.
            # Se recomienda que esta acción esté protegida por permisos de Admin en el endpoint.
            EstadoOperativoEnum.BODEGA,
            EstadoOperativoEnum.DISPONIBLE,
        }
    }

    @classmethod
    def is_transition_allowed(
        cls, current: EstadoOperativoEnum, target: EstadoOperativoEnum
    ) -> bool:
        """
        Verifica si la transición de un estado a otro es legal.
        """
        if current == target:
            return True
            
        allowed = cls.TRANSITIONS.get(current, set())
        return target in allowed

    @classmethod
    def validate_transition(
        cls, current: EstadoOperativoEnum, target: EstadoOperativoEnum
    ) -> None:
        """
        Valida la transición y lanza InvalidStateTransitionError si es ilegal.
        La capa de servicio traduce esta excepción de dominio a HTTPException 400.
        """
        if not cls.is_transition_allowed(current, target):
            raise InvalidStateTransitionError(current.value, target.value)
