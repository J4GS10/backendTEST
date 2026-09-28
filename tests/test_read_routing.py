"""Pruebas de la política READ_STRONG / READ_REPORTING."""
from app.core.read_routing import ReadRoutingService


def test_replica_lag_below_warning_is_suitable(monkeypatch):
    monkeypatch.setattr(
        "app.core.read_routing.settings.DB_REPLICA_LAG_WARNING_SECONDS", 5.0
    )
    monkeypatch.setattr(
        "app.core.read_routing.settings.DB_REPLICA_LAG_CRITICAL_SECONDS", 30.0
    )

    status = ReadRoutingService.classify(
        configured=True,
        available=True,
        is_standby=True,
        lag_seconds=1.25,
    )

    assert status.status == "ok"
    assert status.suitable_for_reporting is True
    assert status.lag_seconds == 1.25


def test_replica_warning_remains_suitable(monkeypatch):
    monkeypatch.setattr(
        "app.core.read_routing.settings.DB_REPLICA_LAG_WARNING_SECONDS", 5.0
    )
    monkeypatch.setattr(
        "app.core.read_routing.settings.DB_REPLICA_LAG_CRITICAL_SECONDS", 30.0
    )

    status = ReadRoutingService.classify(
        configured=True,
        available=True,
        is_standby=True,
        lag_seconds=10.0,
    )

    assert status.status == "warning"
    assert status.suitable_for_reporting is True


def test_replica_critical_lag_requires_writer_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.core.read_routing.settings.DB_REPLICA_LAG_WARNING_SECONDS", 5.0
    )
    monkeypatch.setattr(
        "app.core.read_routing.settings.DB_REPLICA_LAG_CRITICAL_SECONDS", 30.0
    )

    status = ReadRoutingService.classify(
        configured=True,
        available=True,
        is_standby=True,
        lag_seconds=31.0,
    )

    assert status.status == "critical"
    assert status.suitable_for_reporting is False
    assert status.reason == "replica_lag_critical"


def test_read_endpoint_must_be_a_standby():
    status = ReadRoutingService.classify(
        configured=True,
        available=True,
        is_standby=False,
        lag_seconds=0.0,
    )

    assert status.status == "critical"
    assert status.suitable_for_reporting is False
    assert status.reason == "read_endpoint_is_not_standby"


def test_connection_failure_replaces_stale_replica_status():
    service = ReadRoutingService()
    service._last_status = service.classify(
        configured=True,
        available=True,
        is_standby=True,
        lag_seconds=0.0,
    )

    status = service.mark_unavailable("OperationalError")

    assert status.status == "down"
    assert service.last_status.available is False
    assert service.last_status.reason == "OperationalError"
