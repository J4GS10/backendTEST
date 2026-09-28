#!/usr/bin/env bash
# Ciclo de vida de esquema/bootstrap. Este proceso es one-shot y fail-closed.
set -euo pipefail

echo "==> Aplicando migraciones Alembic..."
if [[ "${DB_ENGINE:-postgres}" == "oracle" ]]; then
  alembic -n oracle upgrade head
else
  alembic upgrade head
fi

echo "==> Ejecutando bootstrap idempotente..."
python -m app.init_prod

echo "==> Cargando catálogo mínimo canónico..."
python -m app.seed_min

echo "==> Migración y bootstrap completados."
