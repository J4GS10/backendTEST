#!/usr/bin/env bash
# Entrypoint HTTP de producción; migrator administra el esquema y bootstrap.
set -euo pipefail

echo "==> Arrancando gunicorn (DB administrada por migrator)..."
exec gunicorn app.main:app \
    -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers "${WEB_CONCURRENCY:-4}" \
    --access-logfile - \
    --error-logfile - \
    --timeout 60 \
    --graceful-timeout 30
