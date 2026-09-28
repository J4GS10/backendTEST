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
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.email import email_delivery_metrics
from app.core.limiter import limiter
from app.core.read_routing import read_routing_service
from app.core.storage import storage_service
from app.api.v1.api import api_router
from app.db.resilience import probe_database
from app.db.session import engine, read_engine, reporting_session


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
async def _check_db_rls() -> None:
    """
    Verifica la capa RLS de PostgreSQL (rol restringido + políticas). Sin ella,
    el alcance por sede sigue aplicándose en la aplicación, pero se registra
    como error: la defensa en profundidad está incompleta.
    """
    from app.core.data_scope import set_db_rls_available
    if not settings.DB_RLS_ENABLED or engine.dialect.name != "postgresql":
        set_db_rls_available(False)
        return
    from app.db.rls import check_rls
    try:
        async with engine.connect() as conn:
            ok, reason = await conn.run_sync(check_rls)
    except Exception as exc:  # noqa: BLE001
        ok, reason = False, f"check_failed:{type(exc).__name__}"
    set_db_rls_available(ok)
    if ok:
        log.info("rls.db_layer_active", role=settings.DB_RLS_ROLE)
    else:
        log.error("rls.db_layer_unavailable", reason=reason,
                  hint="python -m app.db.install_rls (ver DEPLOYMENT.md)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("app.startup", env=settings.ENVIRONMENT, project=settings.PROJECT_NAME)
    await _check_db_rls()
    from app.services.scheduled_jobs import start_background_jobs, stop_background_jobs
    jobs = start_background_jobs()
    yield
    await stop_background_jobs(jobs)
    await engine.dispose()
    if read_engine is not engine:
        await read_engine.dispose()
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
    # SECURITY: allow_credentials=False — usamos JWT Bearer en Authorization,
    # no cookies. Activar credentials con origins permisivos sería un anti-patrón
    # (CSRF cross-origin desde apps locales hostiles).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(o).rstrip("/") for o in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["Content-Disposition", "X-Request-ID"],
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
    from app.core.limiter import client_ip_key
    req_id = request.headers.get("x-request-id") or _uuid.uuid4().hex[:16]
    # Reutilizar la misma política segura que el limiter (X-Real-IP > last hop).
    client_ip = client_ip_key(request)
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
    response.headers["Permissions-Policy"] = (
        "geolocation=(), microphone=(), camera=(self), payment=(), usb=(), "
        "interest-cohort=(), browsing-topics=(), fullscreen=(self), "
        "accelerometer=(), gyroscope=(), magnetometer=()"
    )
    if settings.IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
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
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate == "42501":
        # Política RLS o permiso del rol restringido: el registro está fuera
        # del alcance del usuario (la validación de la aplicación no lo atajó).
        log.warning("rls.denied", path=str(request.url), error=str(orig)[:200])
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "SEDE_OUT_OF_SCOPE"},
        )
    log.error("db.error", path=str(request.url), error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "DATABASE_ERROR"},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "VALIDATION_ERROR", "errors": jsonable_encoder(exc.errors())},
    )


# =========================================================================
# ROUTES
# =========================================================================
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness + DB ping. Usar para load balancer / kubernetes."""
    writer_probe = await probe_database(
        engine,
        retries=settings.DB_FAILOVER_PROBE_RETRIES,
        timeout_seconds=settings.DB_CONNECT_TIMEOUT_SECONDS,
        retry_delay_seconds=settings.DB_FAILOVER_RETRY_DELAY_SECONDS,
    )
    db_ok = writer_probe.available
    if not db_ok:
        log.warning("health.db_failed", error=writer_probe.error)

    payload = {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "down",
        "writer_probe_attempts": writer_probe.attempts,
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
    storage_ok: bool | None = None
    writer_probe = await probe_database(
        engine,
        retries=settings.DB_FAILOVER_PROBE_RETRIES,
        timeout_seconds=settings.DB_CONNECT_TIMEOUT_SECONDS,
        retry_delay_seconds=settings.DB_FAILOVER_RETRY_DELAY_SECONDS,
    )
    db_ok = writer_probe.available
    if not db_ok:
        log.warning("health.db_failed", error=writer_probe.error)

    if settings.HAS_READ_REPLICA:
        try:
            async with read_engine.connect() as conn:
                replica_status = await read_routing_service.inspect(conn)
        except Exception as exc:  # noqa: BLE001
            log.warning("health.replica_failed", error=str(exc))
            replica_status = read_routing_service.mark_unavailable(type(exc).__name__)
    else:
        replica_status = read_routing_service.classify(
            configured=False,
            available=False,
            is_standby=None,
            lag_seconds=None,
        )

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

    try:
        storage_ok = await storage_service.health()
    except Exception as exc:  # noqa: BLE001
        log.warning("health.storage_failed", error=str(exc))
        storage_ok = False

    smtp_metrics = email_delivery_metrics()

    optional_degraded = (
        redis_ok is False
        or storage_ok is False
        or smtp_metrics["status"] == "down"
        or (
            replica_status.configured
            and not replica_status.suitable_for_reporting
        )
    )
    status_global = "down" if not db_ok else ("degraded" if optional_degraded else "ok")
    # Solo el writer es dependencia fatal. Réplica y Redis degradan con 200.
    code = 503 if not db_ok else 200
    payload = {
        "status": status_global,
        "components": {
            "database": "ok" if db_ok else "down",
            "writer_database": "ok" if db_ok else "down",
            "writer_probe_attempts": writer_probe.attempts,
            "read_replica": replica_status.status,
            "read_replica_details": replica_status.as_dict(),
            "replica_lag_seconds": replica_status.lag_seconds,
            "redis": "ok" if redis_ok else ("disabled" if redis_ok is None else "down"),
            "storage": "ok" if storage_ok else "down",
            "storage_backend": settings.STORAGE_BACKEND,
            "smtp": smtp_metrics["status"],
            "smtp_details": smtp_metrics,
        },
        "read_routing": read_routing_service.metrics(),
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
        async with reporting_session() as db:
            total_activos = (await db.execute(select(func.count()).select_from(Activo))).scalar() or 0
            total_users_active = (
                await db.execute(
                    select(func.count()).select_from(Usuario).where(Usuario.USU_Estado == True)  # noqa: E712
                )
            ).scalar() or 0
            total_revoked = (await db.execute(select(func.count()).select_from(TokenRevocado))).scalar() or 0
            from app.models.governance import EmailOutbox
            outbox = dict((await db.execute(
                select(EmailOutbox.EOB_Estado, func.count()).group_by(EmailOutbox.EOB_Estado)
            )).all())
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
    lines.append("# HELP inv_email_outbox Correos en la cola persistente por estado")
    lines.append("# TYPE inv_email_outbox gauge")
    for estado in ("PENDIENTE", "ENVIADO", "FALLIDO"):
        lines.append(f'inv_email_outbox{{estado="{estado}"}} {outbox.get(estado, 0)}')
    replica = read_routing_service.last_status
    routing_metrics = read_routing_service.metrics()
    lines.append("# HELP inv_db_replica_available Disponibilidad de la replica de lectura")
    lines.append("# TYPE inv_db_replica_available gauge")
    lines.append(f"inv_db_replica_available {1 if replica.available else 0}")
    lines.append("# HELP inv_db_replica_suitable Apta para lecturas de reporting")
    lines.append("# TYPE inv_db_replica_suitable gauge")
    lines.append(
        f"inv_db_replica_suitable {1 if replica.suitable_for_reporting else 0}"
    )
    lines.append("# HELP inv_db_replica_lag_seconds Lag de aplicacion WAL de la replica")
    lines.append("# TYPE inv_db_replica_lag_seconds gauge")
    lag_value = replica.lag_seconds if replica.lag_seconds is not None else "NaN"
    lines.append(f"inv_db_replica_lag_seconds {lag_value}")
    lines.append("# HELP inv_db_read_fallback_total Fallbacks de reporting al writer")
    lines.append("# TYPE inv_db_read_fallback_total counter")
    lines.append(f"inv_db_read_fallback_total {routing_metrics['fallback_total']}")
    lines.append("# HELP inv_db_replica_reads_total Lecturas dirigidas a la replica")
    lines.append("# TYPE inv_db_replica_reads_total counter")
    lines.append(f"inv_db_replica_reads_total {routing_metrics['replica_reads_total']}")
    storage_available = await storage_service.health()
    lines.append("# HELP inv_storage_available Disponibilidad del object storage")
    lines.append("# TYPE inv_storage_available gauge")
    lines.append(f"inv_storage_available {1 if storage_available else 0}")
    smtp_metrics = email_delivery_metrics()
    lines.append("# HELP inv_smtp_delivery_errors_total Errores de entrega SMTP")
    lines.append("# TYPE inv_smtp_delivery_errors_total counter")
    lines.append(f"inv_smtp_delivery_errors_total {smtp_metrics['failed_total']}")
    lines.append("# HELP inv_smtp_delivery_sent_total Correos entregados por SMTP")
    lines.append("# TYPE inv_smtp_delivery_sent_total counter")
    lines.append(f"inv_smtp_delivery_sent_total {smtp_metrics['sent_total']}")

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.get("/", include_in_schema=False)
async def root():
    return {"service": settings.PROJECT_NAME, "docs": f"{settings.API_V1_STR}/docs"}
