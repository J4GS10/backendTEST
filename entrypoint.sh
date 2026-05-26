#!/usr/bin/env bash
# Entrypoint para producción: aplica migraciones y arranca gunicorn.
set -euo pipefail

echo "==> Aplicando migraciones Alembic..."
alembic upgrade head

echo "==> Bootstrap inicial (idempotente)..."
python -m app.init_prod || echo "WARN: init_prod falló (probablemente ya está inicializado)"

if [ "${SEED_DEMO:-false}" = "true" ]; then
    echo "==> Cargando data demo (idempotente)..."
    python -m app.seed_demo || echo "WARN: seed_demo falló (probablemente ya está cargado)"
fi

echo "==> Arrancando gunicorn..."
exec gunicorn app.main:app \
    -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --workers "${WEB_CONCURRENCY:-4}" \
    --access-logfile - \
    --error-logfile - \
    --timeout 60 \
    --graceful-timeout 30
