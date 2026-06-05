#!/usr/bin/env bash
# Entrypoint para producción: aplica migraciones y arranca gunicorn.
set -euo pipefail

echo "==> Aplicando migraciones Alembic..."
alembic upgrade head

echo "==> Bootstrap inicial (idempotente)..."
python -m app.init_prod || echo "WARN: init_prod falló (probablemente ya está inicializado)"

echo "==> Seed mínimo canónico (estados, tipos de movimiento; idempotente, prod-safe)..."
python -m app.seed_min || echo "WARN: seed_min falló (probablemente ya está cargado)"

if [ "${SEED_DEMO:-false}" = "true" ]; then
    if [ "${ENVIRONMENT:-development}" = "production" ]; then
        echo "ERROR: SEED_DEMO=true es incompatible con ENVIRONMENT=production." >&2
        echo "       Crea usuarios con passwords conocidas. Refuse to start." >&2
        exit 1
    fi
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
