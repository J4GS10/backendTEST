# Herramientas y dependencias

Inventario completo de tecnologías, librerías y herramientas del proyecto, con versión y
propósito. Fuentes: `backend/inventarioTI-backend/requirements.txt`,
`backend/inventarioTI-frontend/package.json`, Dockerfiles y `docker-compose.yml`.

## Backend (Python 3.11)

| Paquete | Versión | Propósito |
|---|---|---|
| fastapi | ≥0.109.0 | Framework web async (REST, OpenAPI, DI) |
| uvicorn[standard] | ≥0.27.0 | Servidor ASGI (desarrollo / worker class) |
| gunicorn | ≥21.2.0 | Gestor de procesos en producción (N workers Uvicorn) |
| sqlalchemy | ≥2.0.25 | ORM + toolkit SQL (async) |
| alembic | ≥1.13.1 | Migraciones de esquema versionadas |
| **psycopg[binary,pool]** | ≥3.1.18 | **Driver PostgreSQL (psycopg 3, async)** |
| aiosqlite | ≥0.20.0 | Driver SQLite async (dev/tests) |
| pydantic | ≥2.6.0 | Validación de datos / schemas |
| pydantic-settings | ≥2.1.0 | Configuración desde `.env` |
| email-validator | ≥2.1.0 | Validación de `EmailStr` |
| python-multipart | ≥0.0.9 | Parsing `multipart/form-data` (subida de adjuntos) |
| python-jose[cryptography] | ≥3.4.0 | Firma/verificación de JWT (sobre CVEs) |
| passlib[argon2,bcrypt] | ≥1.7.4 | Hashing de contraseñas (argon2 primario, bcrypt) |
| bcrypt | ==4.0.1 | Backend bcrypt (pin de compatibilidad) |
| cryptography | ≥43.0.0 | Cifrado de campos (Fernet / MultiFernet) |
| slowapi | ≥0.1.9 | Rate limiting |
| limits[redis] | ≥3.13.0 | Backends de rate limit (memoria/Redis) |
| redis | ≥5.0.0 | Cliente Redis async (caché auth) |
| aiosmtplib | ≥3.0.0 | Envío de email async (SMTP) |
| jinja2 | ≥3.1.0 | Plantillas de email |
| structlog | ≥24.1.0 | Logging estructurado (JSON en prod) |
| python-docx | ≥0.8.11 | Generación de actas Word |
| reportlab | ≥4.1.0 | Generación de actas/PDF |
| pillow | ≥10.3.0 | Imágenes (logo, QR) |
| httpx | ≥0.27.0 | Cliente HTTP async (descarga de logo, tests) |
| pyotp | ≥2.9.0 | TOTP (RFC 6238) para 2FA |
| qrcode | ≥7.4.2 | QR de enrolamiento TOTP |
| pytest, pytest-asyncio | ≥8.0 / ≥0.23 | Testing |
| pip-audit | ≥2.7.0 | Auditoría de vulnerabilidades de dependencias |

## Frontend (Node 20 build · React 19)

| Paquete | Versión | Propósito |
|---|---|---|
| react / react-dom | 19.2 | UI |
| react-router-dom | 7.9 | Routing + RBAC por ruta |
| @mui/material · @mui/icons-material | 7.3 | Componentes Material Design + iconos |
| @emotion/react · @emotion/styled | 11 | CSS-in-JS (motor de MUI) |
| axios | 1.13 | Cliente HTTP + interceptores (refresh transparente) |
| react-hook-form | 7.66 | Formularios |
| @hookform/resolvers · zod | 5 · 4 | Validación de formularios |
| i18next · react-i18next | 25 · 16 | Internacionalización (es/en/it) |
| i18next-browser-languagedetector | 8.2 | Detección de idioma |
| notistack | 3 | Notificaciones (snackbars) |
| jwt-decode | 4 | Decodificar JWT en cliente |
| zustand | 5 | Estado (disponible) |
| **DevDeps** | | |
| typescript | 5.9 | Tipado estricto |
| vite · @vitejs/plugin-react | 7.2 · 5.1 | Bundler / dev server |
| eslint · typescript-eslint | 9 · 8 | Linting |
| eslint-plugin-react-hooks · -refresh | 7 · 0.4 | Reglas de hooks / fast refresh |

## Infraestructura

| Herramienta | Versión | Rol |
|---|---|---|
| Docker / docker-compose | — | Contenedorización y orquestación |
| PostgreSQL | 16-alpine | Base de datos |
| Redis | 7-alpine | Caché de auth + storage de rate-limit |
| Caddy | 2-alpine | Edge, TLS automático, reverse proxy |
| Nginx | 1.27-alpine | Servidor de la SPA + proxy `/api` |
| MailHog | latest | Captura de email en desarrollo (perfil `dev`) |
| Gunicorn + UvicornWorker | — | Servidor de aplicación en producción |

## Tooling de proyecto

- **Makefile** — `up/down/test/backup/restore/health/metrics`.
- **scripts/check_rbac.py** — guard CI: falla si un endpoint mutador no tiene guard de rol.
- **scripts/backup_db.sh** — backup con verificación y opción de sync a S3.
- **.github/workflows/** — CI (pytest + ruff backend; build frontend).
- **Alembic** — `alembic upgrade head` en el arranque (`entrypoint.sh`).
