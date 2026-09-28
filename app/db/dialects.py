"""Capacidades de los motores soportados, aisladas de la lógica de negocio."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseDialect:
    name: str
    sqlalchemy_name: str
    read_only_statement: str | None
    supports_for_update: bool
    supports_replica_lag_probe: bool
    connect_timeout_argument: str | None = None

    def connect_args(self, timeout_seconds: int) -> dict[str, int]:
        if not self.connect_timeout_argument:
            return {}
        return {self.connect_timeout_argument: timeout_seconds}


_DIALECTS = {
    "postgres": DatabaseDialect(
        name="postgres",
        sqlalchemy_name="postgresql",
        read_only_statement="SET TRANSACTION READ ONLY",
        supports_for_update=True,
        supports_replica_lag_probe=True,
        connect_timeout_argument="connect_timeout",
    ),
    "mysql": DatabaseDialect(
        name="mysql",
        sqlalchemy_name="mysql",
        read_only_statement="SET TRANSACTION READ ONLY",
        supports_for_update=True,
        supports_replica_lag_probe=False,
        connect_timeout_argument="connect_timeout",
    ),
    "oracle": DatabaseDialect(
        name="oracle",
        sqlalchemy_name="oracle",
        read_only_statement="SET TRANSACTION READ ONLY",
        supports_for_update=True,
        supports_replica_lag_probe=False,
    ),
    "sqlite": DatabaseDialect(
        name="sqlite",
        sqlalchemy_name="sqlite",
        read_only_statement=None,
        supports_for_update=False,
        supports_replica_lag_probe=False,
    ),
}


def dialect_for(engine_name: str) -> DatabaseDialect:
    """Acepta tanto nombres de configuración como nombres de SQLAlchemy."""
    normalized = engine_name.lower()
    if normalized == "postgresql":
        normalized = "postgres"
    try:
        return _DIALECTS[normalized]
    except KeyError as exc:
        raise ValueError(f"Motor de base de datos no soportado: {engine_name}") from exc

