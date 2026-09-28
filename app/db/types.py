"""SQLAlchemy types with equivalent storage across supported database engines."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import JSON, Text
from sqlalchemy.types import TypeDecorator


class PortableJSON(TypeDecorator[Any]):
    """Store JSON natively where supported and as serialized CLOB on Oracle.

    Oracle 21c supports JSON constraints, but SQLAlchemy's Oracle dialect does
    not compile the generic ``JSON`` type. The application only persists and
    retrieves complete JSON documents, so a CLOB representation preserves the
    contract without leaking engine-specific types into domain models.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):  # noqa: ANN001
        if dialect.name == "oracle":
            return dialect.type_descriptor(Text())
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect):  # noqa: ANN001
        if value is None or dialect.name != "oracle":
            return value
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def process_result_value(self, value: Any, dialect):  # noqa: ANN001
        if value is None or dialect.name != "oracle" or not isinstance(value, str):
            return value
        return json.loads(value)
