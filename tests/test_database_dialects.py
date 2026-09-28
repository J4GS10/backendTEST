"""Pruebas de aislamiento de capacidades entre motores."""
import pytest

from app.db.dialects import dialect_for


@pytest.mark.parametrize("name", ["postgres", "postgresql"])
def test_postgres_capabilities(name):
    dialect = dialect_for(name)

    assert dialect.supports_for_update is True
    assert dialect.supports_replica_lag_probe is True
    assert dialect.read_only_statement == "SET TRANSACTION READ ONLY"
    assert dialect.connect_args(5) == {"connect_timeout": 5}


def test_mysql_and_oracle_are_prepared_without_postgres_lag_sql():
    mysql = dialect_for("mysql")
    oracle = dialect_for("oracle")

    assert mysql.supports_for_update is True
    assert oracle.supports_for_update is True
    assert mysql.supports_replica_lag_probe is False
    assert oracle.supports_replica_lag_probe is False
    assert mysql.read_only_statement
    assert oracle.read_only_statement


def test_sqlite_disables_unsupported_features():
    dialect = dialect_for("sqlite")

    assert dialect.supports_for_update is False
    assert dialect.supports_replica_lag_probe is False
    assert dialect.read_only_statement is None


def test_unknown_engine_fails_explicitly():
    with pytest.raises(ValueError, match="no soportado"):
        dialect_for("unknown")
