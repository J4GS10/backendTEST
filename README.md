# Sistema de Inventario TI — Backend

API del sistema de inventario de TI: gestión de activos, asignaciones/trazabilidad,
software y licencias, consumibles, compras/proveedores/garantías, mantenimiento,
usuarios, 2FA y auditoría.

**Stack:** FastAPI (async) · SQLAlchemy 2 · PostgreSQL 16 · Redis · Alembic · JWT + 2FA ·
contenedorizado (Docker) detrás de Caddy. Frontend (React) en el repo hermano
[`inventario-ti-frontend`](https://github.com/J4GS10/inventario-ti-frontend).

---

## 🚀 Despliegue

Para levantar **todo el stack en limpio** (sin datos de prueba, solo los *seeds*
necesarios), sigue la guía paso a paso:

### → **[DEPLOYMENT.md](DEPLOYMENT.md)** — guía de despliegue completa

Arranque rápido (resumen — los detalles y la generación de secretos están en la guía):

```bash
mkdir inventario-ti && cd inventario-ti
git clone https://github.com/J4GS10/inventario-ti-backend.git
git clone https://github.com/J4GS10/inventario-ti-frontend.git
cd inventario-ti-backend/deploy
cp .env.example .env          # genera y pega los secretos (ver DEPLOYMENT.md §4)
docker compose up -d --build  # migraciones + sa + seed mínimo canónico, sin data demo
```

El kit de despliegue (compose + Caddyfile + plantilla `.env`) está en
[`deploy/`](deploy).

---

## 📚 Documentación

Toda la documentación del proyecto está en [`docs/`](docs):

| Documento | Contenido |
|---|---|
| [docs/README.md](docs/README.md) | Índice general de la documentación |
| [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) | Arquitectura, stack y patrón por capas |
| [docs/BACKEND.md](docs/BACKEND.md) | Estructura del backend, módulos, core, migraciones, tests |
| [docs/FRONTEND.md](docs/FRONTEND.md) | Frontend React/TS (theming WCAG, i18n, RBAC) |
| [docs/API.md](docs/API.md) | Referencia de los endpoints (generada del OpenAPI) |
| [docs/HERRAMIENTAS.md](docs/HERRAMIENTAS.md) | Inventario de dependencias y herramientas |
| [docs/SEGURIDAD.md](docs/SEGURIDAD.md) | JWT, RBAC, 2FA, rate-limit, auditoría, cifrado |
| [docs/RBAC_MATRIX.md](docs/RBAC_MATRIX.md) | Matriz rol ↔ endpoint |
| [docs/ORACLE_MIGRATION_RUNBOOK.md](docs/ORACLE_MIGRATION_RUNBOOK.md) | Runbook para migrar la BD a Oracle |

---

## 🛠️ Desarrollo

```bash
# Tests (138)
docker compose -f deploy/docker-compose.yml exec backend python -m pytest tests/
# Guard de RBAC (CI)
docker compose -f deploy/docker-compose.yml exec backend python scripts/check_rbac.py
# Migraciones
docker compose -f deploy/docker-compose.yml exec backend alembic upgrade head
```

Para datos de demostración en un entorno de desarrollo (NO producción), arranca con
`SEED_DEMO=true` y `ENVIRONMENT` distinto de `production`.

---

## 📂 Estructura

```
app/
├── api/v1/endpoints/   # endpoints REST por dominio
├── services/           # lógica de negocio (transacciones, auditoría)
├── repositories/       # acceso a datos
├── models/             # ORM SQLAlchemy
├── schemas/            # Pydantic (entrada/salida)
├── core/               # config, seguridad, caché, email, rate-limit
├── alembic/versions/   # migraciones
├── init_prod.py        # bootstrap del primer SUPER_ADMIN
└── seed_min.py         # seed canónico (estados, tipos) — sin data demo
deploy/                 # docker-compose + Caddyfile + .env.example
docs/                   # documentación del proyecto
DEPLOYMENT.md           # guía de despliegue
```

---

## 🔒 Seguridad

JWT (access + refresh en cookie HttpOnly), RBAC de 4 roles
(`SUPER_ADMIN`/`ADMIN_TI`/`TECNICO`/`CONSULTA`), 2FA obligatorio para roles admin,
account lockout, rate-limiting, auditoría append-only y cifrado de campos sensibles.
Ver [docs/SEGURIDAD.md](docs/SEGURIDAD.md) y [SECURITY.md](SECURITY.md).
