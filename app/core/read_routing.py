"""Política central de lecturas strong y reporting."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text

from app.core.config import settings
from app.db.dialects import dialect_for

log = structlog.get_logger("read_routing")
database_dialect = dialect_for("sqlite" if settings.IS_SQLITE else settings.DB_ENGINE)


@dataclass(frozen=True)
class ReplicaStatus:
    configured: bool
    available: bool
    suitable_for_reporting: bool
    status: str
    lag_seconds: float | None = None
    is_standby: bool | None = None
    reason: str | None = None
    checked_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReadRoutingService:
    """Mide la réplica y decide entre READ_REPORTING y READ_STRONG."""

    _REPLICA_STATUS_SQL = text(
        """
        SELECT
            pg_is_in_recovery() AS is_standby,
            CASE
                WHEN pg_last_wal_receive_lsn() IS NULL THEN NULL
                WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() THEN 0.0
                WHEN pg_last_xact_replay_timestamp() IS NULL THEN NULL
                ELSE GREATEST(
                    0.0,
                    EXTRACT(EPOCH FROM (
                        clock_timestamp() - pg_last_xact_replay_timestamp()
                    ))
                )
            END AS lag_seconds
        """
    )

    def __init__(self) -> None:
        self._fallback_total = 0
        self._replica_reads_total = 0
        self._fallback_reasons: dict[str, int] = {}
        self._last_status = ReplicaStatus(
            configured=settings.HAS_READ_REPLICA,
            available=False,
            suitable_for_reporting=False,
            status="unknown" if settings.HAS_READ_REPLICA else "disabled",
        )

    @staticmethod
    def classify(
        *,
        configured: bool,
        available: bool,
        is_standby: bool | None,
        lag_seconds: float | None,
        reason: str | None = None,
    ) -> ReplicaStatus:
        checked_at = datetime.now(timezone.utc).isoformat()
        if not configured:
            return ReplicaStatus(
                configured=False,
                available=False,
                suitable_for_reporting=False,
                status="disabled",
                reason="not_configured",
                checked_at=checked_at,
            )
        if not available:
            return ReplicaStatus(
                configured=True,
                available=False,
                suitable_for_reporting=False,
                status="down",
                reason=reason or "connection_failed",
                checked_at=checked_at,
            )
        if is_standby is False:
            return ReplicaStatus(
                configured=True,
                available=True,
                suitable_for_reporting=False,
                status="critical",
                lag_seconds=lag_seconds,
                is_standby=False,
                reason="read_endpoint_is_not_standby",
                checked_at=checked_at,
            )
        if lag_seconds is None:
            return ReplicaStatus(
                configured=True,
                available=True,
                suitable_for_reporting=False,
                status="critical",
                is_standby=is_standby,
                reason="replica_lag_unknown",
                checked_at=checked_at,
            )

        lag = max(0.0, float(lag_seconds))
        if lag >= settings.DB_REPLICA_LAG_CRITICAL_SECONDS:
            status = "critical"
            suitable = False
            reason = "replica_lag_critical"
        elif lag >= settings.DB_REPLICA_LAG_WARNING_SECONDS:
            status = "warning"
            suitable = True
            reason = "replica_lag_warning"
        else:
            status = "ok"
            suitable = True
            reason = None
        return ReplicaStatus(
            configured=True,
            available=True,
            suitable_for_reporting=suitable,
            status=status,
            lag_seconds=lag,
            is_standby=is_standby,
            reason=reason,
            checked_at=checked_at,
        )

    async def inspect(self, connection: Any) -> ReplicaStatus:
        """Consulta el standby con timeout corto y actualiza el último estado."""
        if not settings.HAS_READ_REPLICA:
            status = self.classify(
                configured=False,
                available=False,
                is_standby=None,
                lag_seconds=None,
            )
            self._last_status = status
            return status
        if not database_dialect.supports_replica_lag_probe:
            status = self.classify(
                configured=True,
                available=False,
                is_standby=None,
                lag_seconds=None,
                reason="lag_probe_not_implemented_for_engine",
            )
            self._last_status = status
            return status

        try:
            async with asyncio.timeout(settings.DB_REPLICA_CHECK_TIMEOUT_SECONDS):
                result = await connection.execute(self._REPLICA_STATUS_SQL)
                row = result.mappings().one()
            status = self.classify(
                configured=True,
                available=True,
                is_standby=bool(row["is_standby"]),
                lag_seconds=(
                    float(row["lag_seconds"])
                    if row["lag_seconds"] is not None
                    else None
                ),
            )
        except Exception as exc:  # noqa: BLE001 - health probe must degrade safely
            status = self.classify(
                configured=True,
                available=False,
                is_standby=None,
                lag_seconds=None,
                reason=type(exc).__name__,
            )
            log.warning("read_replica.probe_failed", error=str(exc))
        self._last_status = status
        return status

    def record_replica_read(self) -> None:
        self._replica_reads_total += 1

    def record_fallback(self, reason: str) -> None:
        self._fallback_total += 1
        self._fallback_reasons[reason] = self._fallback_reasons.get(reason, 0) + 1
        log.warning("read_replica.fallback_to_writer", reason=reason)

    def mark_unavailable(self, reason: str) -> ReplicaStatus:
        """Evita publicar como sano el último estado cuando falla el connect."""
        status = self.classify(
            configured=self._last_status.configured or settings.HAS_READ_REPLICA,
            available=False,
            is_standby=None,
            lag_seconds=None,
            reason=reason,
        )
        self._last_status = status
        return status

    @property
    def last_status(self) -> ReplicaStatus:
        return self._last_status

    def metrics(self) -> dict[str, Any]:
        return {
            "fallback_total": self._fallback_total,
            "replica_reads_total": self._replica_reads_total,
            "fallback_reasons": dict(self._fallback_reasons),
        }


read_routing_service = ReadRoutingService()
