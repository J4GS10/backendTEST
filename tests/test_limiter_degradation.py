"""El rate-limit debe degradar a memoria local si Redis deja de responder."""
from app.core.limiter import limiter_options


def test_redis_limiter_enables_in_memory_fallback():
    options = limiter_options("redis://:secret@redis:6379/0")

    assert options["in_memory_fallback_enabled"] is True
    assert options["swallow_errors"] is True
    assert options["storage_uri"].startswith("redis://")


def test_local_limiter_does_not_require_redis():
    options = limiter_options(None)

    assert "storage_uri" not in options
    assert "in_memory_fallback_enabled" not in options
