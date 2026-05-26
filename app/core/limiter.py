"""
Limiter compartido (evita imports circulares main <-> endpoints).

IMPORTANTE: el backend está detrás de Caddy + Nginx, por lo que
`request.client.host` siempre es la IP del contenedor nginx (la misma para
todos). Si usáramos `get_remote_address` el rate limit sería GLOBAL en vez
de por-cliente. Por eso derivamos la IP real del cliente desde la cabecera
`X-Forwarded-For` que nginx inyecta (`proxy_add_x_forwarded_for`).

Confiamos en X-Forwarded-For porque el backend NO está expuesto al host:
solo es accesible vía la red interna de Docker (nginx), que es el único que
puede setear esa cabecera. Si en el futuro el backend se expusiera
directamente, habría que validar contra una lista de proxies confiables.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings


def client_ip_key(request: Request) -> str:
    """IP real del cliente: primer valor de X-Forwarded-For, o fallback al peer."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # Formato: "client, proxy1, proxy2" → el cliente es el primero.
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return get_remote_address(request)


_limiter_kwargs = {
    "key_func": client_ip_key,
    "default_limits": [settings.RATE_LIMIT_DEFAULT],
}
# Si hay REDIS_URL, el rate-limit es compartido entre workers/réplicas.
# Si no, fallback a memoria local del proceso (válido para single-worker dev).
if settings.REDIS_URL:
    _limiter_kwargs["storage_uri"] = settings.REDIS_URL

limiter = Limiter(**_limiter_kwargs)
