"""Monedas admitidas para montos (costos de activos, mantenimientos y compras).

Cada monto se guarda en la moneda en que se pagó, sin convertir: un activo
comprado en dólares conserva su costo en USD y uno en quetzales en GTQ. Los
totales se agrupan por moneda; nunca se suman montos de monedas distintas.
"""
from typing import Annotated

from pydantic import AfterValidator

SUPPORTED_CURRENCIES = ("GTQ", "USD", "CHF")
DEFAULT_CURRENCY = "GTQ"

# Condición SQL reutilizable en los CheckConstraint de cada tabla.
CURRENCY_SQL_LIST = ", ".join(f"'{c}'" for c in SUPPORTED_CURRENCIES)


def normalize_currency(value: str) -> str:
    code = (value or "").strip().upper()
    if code not in SUPPORTED_CURRENCIES:
        raise ValueError("UNSUPPORTED_CURRENCY")
    return code


# Tipo Pydantic: acepta minúsculas y rechaza monedas no admitidas.
CurrencyCode = Annotated[str, AfterValidator(normalize_currency)]
