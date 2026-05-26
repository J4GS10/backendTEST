"""Punto de entrada de la aplicación FastAPI."""
from __future__ import annotations

import logging
import sys
import asyncio
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.limiter import limiter
from app.api.v1.api import api_router
from app.db.session import engine


# =========================================================================
# LOGGING (structlog)
# =========================================================================
def _configure_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if settings.IS_PRODUCTION:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


_configure_logging()
log = structlog.get_logger(__name__)


# =========================================================================
# LIFESPAN
# =========================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("app.startup", env=settings.ENVIRONMENT, project=settings.PROJECT_NAME)
    yield
    await engine.dispose()
    log.info("app.shutdown")


# =========================================================================
# APP
# =========================================================================
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if not settings.IS_PRODUCTION or settings.DEBUG else None,
    docs_url=f"{settings.API_V1_STR}/docs" if not settings.IS_PRODUCTION or settings.DEBUG else None,
    redoc_url=f"{settings.API_V1_STR}/redoc" if not settings.IS_PRODUCTION or settings.DEBUG else None,
    description="API REST Sistema Inventario TI",
    version="1.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse(
    status_code=429, content={"detail": "RATE_LIMIT_EXCEEDED"}
))
app.add_middleware(SlowAPIMiddleware)


# =========================================================================
# CORS
# =========================================================================
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(o).rstrip("/") for o in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )


# =========================================================================
# REQUEST CONTEXT (request_id, client_ip, method, path) en cada log
# =========================================================================
@app.middleware("http")
async def request_context(request: Request, call_next):
    """
    Cada request:
    - Lee/genera un X-Request-ID.
    - Bind a structlog contextvars para que TODOS los logs del request lo incluyan.
    - Lo devuelve en la respuesta para correlación cliente↔servidor.
    """
    import uuid as _uuid
    req_id = request.headers.get("x-request-id") or _uuid.uuid4().hex[:16]
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=req_id,
        client_ip=client_ip,
        method=request.method,
        path=request.url.path,
    )
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response


# =========================================================================
# SECURITY HEADERS
# =========================================================================
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if settings.IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# =========================================================================
# EXCEPTION HANDLERS
# =========================================================================
@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    log.warning("db.integrity_error", path=str(request.url), error=str(exc.orig))
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "INTEGRITY_CONSTRAINT_VIOLATED"},
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError):
    log.error("db.error", path=str(request.url), error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "DATABASE_ERROR"},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "VALIDATION_ERROR", "errors": exc.errors()},
    )


# =========================================================================
# ROUTES
# =========================================================================
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness + DB ping. Usar para load balancer / kubernetes."""
    db_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # noqa: BLE001
        log.warning("health.db_failed", error=str(exc))

    payload = {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "down",
        "version": "1.2.0",
        "environment": settings.ENVIRONMENT,
    }
    return JSONResponse(status_code=200 if db_ok else 503, content=payload)


@app.get("/health/full", tags=["Health"])
async def health_full():
    """
    Health extendido: DB + Redis (si está configurado). Útil para sondas detalladas
    y dashboards. 200 si todo OK; 503 si algún componente crítico falla.
    """
    db_ok = False
    redis_ok: bool | None = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # noqa: BLE001
        log.warning("health.db_failed", error=str(exc))

    try:
        from app.core.cache import get_redis
        r = get_redis()
        if r is not None:
            await r.ping()
            redis_ok = True
        else:
            redis_ok = None  # no configurado, no es failure
    except Exception as exc:  # noqa: BLE001
        log.warning("health.redis_failed", error=str(exc))
        redis_ok = False

    status_global = "ok" if db_ok and (redis_ok is not False) else "degraded"
    code = 200 if status_global == "ok" else 503
    payload = {
        "status": status_global,
        "components": {
            "database": "ok" if db_ok else "down",
            "redis": "ok" if redis_ok else ("disabled" if redis_ok is None else "down"),
        },
        "version": "1.2.0",
        "environment": settings.ENVIRONMENT,
    }
    return JSONResponse(status_code=code, content=payload)


@app.get("/metrics", tags=["Health"])
async def metrics():
    """
    Métricas en formato texto (compatible Prometheus). Sin lib externa.
    Cuenta:
      - activos totales y por estado
      - usuarios activos
      - tokens revocados pendientes de purga
    """
    from sqlalchemy import func
    from app.models.core import Activo
    from app.models.organization import Usuario
    from app.models.governance import TokenRevocado
    from sqlalchemy.future import select

    lines: list[str] = []
    try:
        async with engine.connect() as conn:
            total_activos = (await conn.execute(select(func.count()).select_from(Activo))).scalar() or 0
            total_users_active = (
                await conn.execute(
                    select(func.count()).select_from(Usuario).where(Usuario.USU_Estado == True)  # noqa: E712
                )
            ).scalar() or 0
            total_revoked = (await conn.execute(select(func.count()).select_from(TokenRevocado))).scalar() or 0
    except Exception as exc:  # noqa: BLE001
        log.warning("metrics.query_failed", error=str(exc))
        return JSONResponse(status_code=503, content={"status": "metrics_unavailable"})

    lines.append("# HELP inv_activos_total Total de activos registrados")
    lines.append("# TYPE inv_activos_total gauge")
    lines.append(f"inv_activos_total {total_activos}")
    lines.append("# HELP inv_usuarios_activos Total de usuarios con USU_Estado=true")
    lines.append("# TYPE inv_usuarios_activos gauge")
    lines.append(f"inv_usuarios_activos {total_users_active}")
    lines.append("# HELP inv_tokens_revocados Filas en SYS_TOKEN_REVOCADO (pendientes de purga)")
    lines.append("# TYPE inv_tokens_revocados gauge")
    lines.append(f"inv_tokens_revocados {total_revoked}")

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.get("/", include_in_schema=False)
async def root():
    return {"service": settings.PROJECT_NAME, "docs": f"{settings.API_V1_STR}/docs"}
