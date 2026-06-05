# Documentación — Sistema de Inventario TI (Lombardi)

Sistema de inventario de TI: gestión de activos, asignaciones/trazabilidad, software y
licencias, consumibles, compras/proveedores/garantías, mantenimiento, usuarios y
auditoría. Stack **FastAPI + React + PostgreSQL + Redis + Caddy**, contenedorizado.

## Índice

| Documento | Contenido |
|---|---|
| [ARQUITECTURA.md](ARQUITECTURA.md) | Visión general, diagrama de componentes, stack y patrón por capas |
| [BACKEND.md](BACKEND.md) | FastAPI: estructura, módulos, capas, core/infra, migraciones, tests |
| [FRONTEND.md](FRONTEND.md) | React/TS: estructura, features, theming WCAG, i18n, routing/RBAC |
| [HERRAMIENTAS.md](HERRAMIENTAS.md) | Inventario completo de herramientas y dependencias con versiones |
| [API.md](API.md) | Referencia de los 203 endpoints (generada del OpenAPI) |
| [SEGURIDAD.md](SEGURIDAD.md) | JWT, RBAC, 2FA, rate-limit, auditoría, cifrado, headers |
| [MIGRACION_ORACLE_21C.md](MIGRACION_ORACLE_21C.md) | Viabilidad y cambios para migrar a Oracle 21c (análisis) |
| [ORACLE_MIGRATION_RUNBOOK.md](ORACLE_MIGRATION_RUNBOOK.md) | **Runbook ejecutable** paso a paso para hacer la migración a Oracle |
| [RBAC_MATRIX.md](RBAC_MATRIX.md) | Matriz rol ↔ endpoint |
| [../SESSION_PROGRESS.md](../SESSION_PROGRESS.md) | Bitácora histórica de cambios (§1–§20) |

## Arranque rápido

```bash
# 1. Variables de entorno (copiar y editar)
cp .env.example .env          # editar SECRET_KEY, FIELD_ENCRYPTION_KEY, passwords, SMTP

# 2. Levantar todo el stack (build + migraciones automáticas)
docker compose up -d --build

# 3. Verificar salud
docker compose ps                                   # 5 servicios healthy
curl -sk https://localhost/ -o /dev/null -w "%{http_code}\n"   # 200

# 4. Tests del backend
docker exec lombardi-backend-1 python -m pytest tests/         # 138 verdes

# 5. Build del frontend (type-check + bundle)
cd backend/inventarioTI-frontend && npm run build
```

Acceso: la app se sirve por **Caddy** en `https://localhost` (TLS automático). El
frontend (Nginx interno) proxya `/api/*` al backend. La base de datos y Redis solo
son accesibles por la red interna de Docker.

## Servicios (docker-compose)

| Servicio | Imagen | Rol |
|---|---|---|
| `caddy` | caddy:2-alpine | Edge/TLS, reverse proxy público (80/443) |
| `frontend` | build (Nginx) | SPA React + proxy `/api` → backend |
| `backend` | build (Gunicorn/Uvicorn) | API FastAPI (8000, interno) |
| `db` | postgres:16-alpine | Base de datos |
| `redis` | redis:7-alpine | Caché de auth + storage de rate-limit |
| `mailhog` (perfil dev) | mailhog/mailhog | Captura de emails en desarrollo |

## Roles del sistema

`SUPER_ADMIN` (total + auditoría/config) · `ADMIN_TI` (gestión completa) ·
`TECNICO` (operación de campo) · `CONSULTA` (solo lectura). 2FA obligatorio para
`SUPER_ADMIN` y `ADMIN_TI`.

## Comandos útiles (Makefile)

`make up` · `make down` · `make test` · `make backup` · `make restore` ·
`make health` · `make metrics`.
