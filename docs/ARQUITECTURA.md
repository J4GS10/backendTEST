# Arquitectura

## Visión general

Aplicación web de 3 capas, contenedorizada, con frontend SPA desacoplado del backend
por una API REST versionada (`/api/v1`).

```
                          Internet
                             │  HTTPS (TLS automático)
                       ┌─────▼─────┐
                       │   Caddy   │  edge / reverse proxy (80/443)
                       └─────┬─────┘
                             │ red interna Docker
                  ┌──────────▼───────────┐
                  │  frontend (Nginx)    │  SPA React (estáticos) + proxy /api
                  └──────────┬───────────┘
                             │ /api/* → backend:8000
                  ┌──────────▼───────────┐        ┌───────────┐
                  │  backend (FastAPI)   │◄───────►│   redis   │  caché auth + rate-limit
                  │  Gunicorn+Uvicorn    │        └───────────┘
                  └──────────┬───────────┘
                             │ SQLAlchemy async (psycopg3)
                       ┌─────▼─────┐
                       │ postgres  │  16
                       └───────────┘
```

## Stack tecnológico

| Capa | Tecnología | Versión |
|---|---|---|
| Frontend | React + TypeScript + Vite | React 19, TS 5.9, Vite 7 |
| UI | Material UI (MUI) + Emotion | MUI 7 |
| Estado/datos | Context API, axios, react-hook-form + Zod | axios 1.13 |
| i18n | i18next / react-i18next | es · en · it |
| Backend | FastAPI (async) | 0.109+ |
| ORM | SQLAlchemy (async) | 2.0+ |
| Driver BD | psycopg 3 (`postgresql+psycopg`) | 3.1+ |
| Migraciones | Alembic | 1.13+ |
| Base de datos | PostgreSQL | 16 |
| Caché | Redis (redis.asyncio) | 7 |
| Auth | JWT (python-jose), passlib (argon2/bcrypt) | — |
| 2FA | pyotp (TOTP) + Email OTP + qrcode | — |
| Rate limit | SlowAPI + limits (Redis) | — |
| Email | aiosmtplib + Jinja2 | — |
| Documentos | python-docx (Word) + reportlab (PDF) | — |
| Cifrado | cryptography (Fernet / MultiFernet) | — |
| Logging | structlog (JSON en prod) | — |
| Edge | Caddy 2 | — |
| Runtime | Python 3.11 · Node 20 (build) · Nginx 1.27 | — |

## Patrón por capas (backend)

```
HTTP request
   │
   ▼  app/api/v1/endpoints/*.py      ← validación de entrada (Pydantic), RBAC (deps), HTTP
endpoint
   │
   ▼  app/services/*.py             ← lógica de negocio, transacciones (@transactional /
service                                commit_or_409), auditoría, invariantes, email post-commit
   │
   ▼  app/repositories/*.py         ← acceso a datos (consultas SQLAlchemy, sin commit)
repository
   │
   ▼  app/models/*.py               ← modelos ORM (tablas, relaciones, constraints)
model
```

- **Schemas** (`app/schemas/*.py`): contratos Pydantic de entrada/salida, con validación
  (longitudes, rangos, formatos) alineada a la BD.
- **Core** (`app/core/*.py`): infraestructura transversal (config, seguridad, caché,
  rate-limit, email, errores, decorador transaccional).
- La transacción y el manejo de `IntegrityError → 409` están centralizados; el email es
  best-effort **post-commit** (un fallo de SMTP nunca revierte la operación).

## Patrón por feature (frontend)

Cada módulo de `src/features/<X>/` agrupa:
- `XPage.tsx` — pantalla principal (tabla/lista, filtros, estado local).
- `XDialog.tsx` — modal de crear/editar (react-hook-form).
- `XService.ts` — capa de API (axios) para ese dominio.
- Tipos en `src/types/`.

El cliente axios centraliza la inyección del `Bearer`, el **refresh transparente** del
token (cookie HttpOnly) y el redireccionamiento a login ante un 401 irrecuperable.

## Flujo de datos de configuración visual

`GET /gov/config` (público) → `ConfigContext` → `App` → `createAppTheme(primario,
secundario, fondo)` → tema MUI con **contraste WCAG calculado** sobre el color de fondo.

## Despliegue

- **Build**: Docker multi-stage (backend: builder + runtime no-root uid 1001;
  frontend: Node build → Nginx).
- **Arranque** (`entrypoint.sh`): `alembic upgrade head` → bootstrap de super admin
  (`init_prod`) → (seed demo solo si no es producción) → Gunicorn con N workers.
- **Volúmenes persistentes**: `postgres_data` (BD), `adjuntos_data` (`/app/uploads`),
  datos de Redis.
- **Salud**: `/health` (DB), `/health/full` (DB+Redis), `/metrics` (Prometheus),
  bloqueados en el edge salvo red interna.
