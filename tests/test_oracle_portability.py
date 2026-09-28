"""Structural checks for the Oracle 21c schema lineage."""
from sqlalchemy.dialects import oracle
from sqlalchemy.schema import CreateTable

from app.core.config import settings
from app.db.base import Base
from app.db.types import PortableJSON


def test_oracle_dsn_is_normalized_for_the_async_driver():
    assert settings._normalize_dsn("oracle://user:pass@db:1521/?service_name=FREEPDB1") == (
        "oracle+oracledb_async://user:pass@db:1521/?service_name=FREEPDB1"
    )


def test_all_model_tables_compile_for_oracle_21c():
    dialect = oracle.dialect()

    for table in Base.metadata.sorted_tables:
        CreateTable(table).compile(dialect=dialect)


def test_portable_json_uses_clob_serialization_on_oracle():
    value = {"event": "created", "items": [1, 2]}
    dialect = oracle.dialect()
    json_type = PortableJSON()

    stored = json_type.process_bind_param(value, dialect)

    assert isinstance(stored, str)
    assert json_type.process_result_value(stored, dialect) == value
