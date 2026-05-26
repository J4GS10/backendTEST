# =========================================================================
# Imagen de PRODUCCIÓN — multi-stage, sin --reload, usuario no-root
# =========================================================================

# --------- Stage 1: builder ---------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt


# --------- Stage 2: runtime ---------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/appuser/.local/bin:$PATH

# Librería runtime de Postgres (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1001 -s /bin/bash appuser

WORKDIR /app

# Copiamos dependencias del builder
COPY --from=builder /root/.local /home/appuser/.local

COPY --chown=appuser:appuser . .

# Permisos de ejecución para el entrypoint
RUN chmod +x /app/entrypoint.sh

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8000/health || exit 1

# Aplica migraciones + bootstrap + arranca gunicorn.
ENTRYPOINT ["/app/entrypoint.sh"]
