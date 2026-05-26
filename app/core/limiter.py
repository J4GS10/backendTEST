"""
Limiter compartido (evita imports circulares main <-> endpoints).

SEGURIDAD — Política de IP de cliente:
El backend está detrás de Caddy → Nginx → backend. `request.client.host` siempre
es la IP del contenedor Nginx, así que usar `get_remote_address` haría que el
rate-limit fuera GLOBAL en vez de por-cliente.

NO confiamos en `X-Forwarded-For` "tal cual" porque históricamente nginx
anexaba a esa cabecera (`$proxy_add_x_forwarded_for`) lo que el cliente
enviara, permitiendo a un atacante spoofear el leftmost IP y burlar el rate
limit del login rotando IPs falsas.

La política actual:
  1. Preferimos `X-Real-IP` → nginx la SOBREESCRIBE con `$remote_addr` (la IP
     del peer real, que es Caddy). Es un único valor controlado por nginx.
  2. Como fallback usamos el ÚLTIMO valor de `X-Forwarded-For` (el más
     reciente, añadido por nuestro propio proxy) en vez del primero.
  3. Sólo si nada de lo anterior está, usamos `request.client.host`.

Si el backend se expusiera directamente al host (sin proxy), habría que
deshabilitar esta lógica o validar contra una lista de proxies confiables
vía Starlette `ProxiedHeadersMiddleware` o `forwarded_allow_ips` de uvicorn.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings


def client_ip_key(request: Request) -> str:
    """IP real del cliente. Ver docstring del módulo para la política completa."""
    # 1. X-Real-IP — nginx la sobreescribe con la IP del peer (Caddy). Confiable.
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()

    # 2. X-Forwarded-For: tomar el ÚLTIMO valor (el añadido por el proxy más
    # cercano al backend), no el primero. Cualquier "primer valor" puede haber
    # sido inyectado por el cliente.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if parts:
            return parts[-1]

    # 3. Fallback: peer directo.
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
