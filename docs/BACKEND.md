# Backend (FastAPI)

Raíz: `backend/inventarioTI-backend/`. Python 3.11. API async, versionada en `/api/v1`.

## Estructura

```
app/
├── main.py                # App FastAPI, middlewares, CORS, security headers, /health, /metrics
├── api/
│   ├── deps.py            # get_current_user, RoleChecker (RBAC), PaginationParams, IP/UA
│   ├── idempotency.py     # Guard de idempotencia (cabecera Idempotency-Key)
│   └── v1/
│       ├── api.py         # Router raíz: incluye y prefija cada módulo
│       └── endpoints/     # 1 archivo por dominio (login, twofactor, organization,
│                          #   location, catalogs, core, traceability, software,
│                          #   maintenance, consumable, attachment, procurement,
│                          #   export, stats, governance)
├── services/              # Lógica de negocio (1 por dominio) + documents.py (actas)
├── repositories/          # Acceso a datos (consultas SQLAlchemy)
├── models/                # ORM (core, catalogs, organization, location, software,
│                          #   traceability, governance, attachment, consumable, procurement)
├── schemas/               # Pydantic v2 (entrada/salida)
├── core/                  # config, security, cache, limiter, transactional, email, errors
├── db/                    # base.py (DeclarativeBase), session.py (engine async, get_db)
├── alembic/versions/      # 23 migraciones versionadas
├── init_prod.py           # Bootstrap del primer SUPER_ADMIN (idempotente)
├── seed_demo.py           # Datos demo (rechazado en producción)
└── purge_security.py      # Purga de tokens revocados / OTPs vencidos
scripts/check_rbac.py      # Guard CI: 0 mutadores sin guard de rol
tests/                     # 24 archivos, 138 tests (pytest + pytest-asyncio)
```

## Módulos de dominio

| Prefijo | Módulo | Qué gestiona |
|---|---|---|
| `/login`, `/me` | Autenticación | Login OAuth2, refresh (cookie), logout, /me, reset de contraseña |
| `/me/2fa` | 2FA/MFA | Enrolamiento TOTP/Email, recovery codes, desactivar |
| `/org` | Organización | Usuarios, personas, departamentos, cargos |
| `/geo` | Ubicación | País→Estado→Municipio→Sede→Edificio→Nivel→Área (cascada) |
| `/cat` | Catálogos | Marcas, modelos, tipos de activo/conexión/especificación, estados operativos |
| `/core` | Inventario | Activos + especificaciones técnicas (RAM, disco, batería…) |
| `/trazabilidad` | Trazabilidad | Movimientos (asignación/devolución/transferencia), offboarding, actas |
| `/soft` | Software | Software, licencias (con clave cifrada), instalaciones por activo |
| `/mantenimiento` | Mantenimiento | Tickets, detalles, cierre |
| `/consumibles` | Consumibles | Alta, entrada/salida de stock, historial, alerta de bajo stock |
| `/adjuntos` | Adjuntos | Archivos por activo u orden (factura, foto, acta) |
| `/compras` | Compras | Proveedores, órdenes, recepción "lazo cerrado", garantías |
| `/stats` | Dashboard | KPIs e indicadores |
| `/export` | Exportación | CSV de activos, movimientos, consumibles, proveedores, órdenes, auditoría |
| `/gov` | Gobierno | Configuración visual (colores/logo/actas), auditoría |

## Core / infraestructura (`app/core/`)

- **config.py** — `Settings` (pydantic-settings) desde `.env`. Construye
  `SQLALCHEMY_DATABASE_URI` (`postgresql+psycopg://…`, o `sqlite+aiosqlite` si
  `POSTGRES_SERVER=sqlite`). Variables clave abajo.
- **security.py** — hashing (argon2/bcrypt + dummy anti-timing), JWT (access/refresh con
  `jti`/`iat`), challenge 2FA, reset tokens, TOTP/Email-OTP, recovery codes, cifrado de
  campos (Fernet/MultiFernet con rotación).
- **cache.py** — Redis async (`cache_get/set/delete`); no-op si no hay Redis.
- **limiter.py** — SlowAPI; clave de IP segura (X-Real-IP › último hop XFF › peer).
- **transactional.py** — `@transactional` y `commit_or_409` (centralizan commit/rollback
  y `IntegrityError → 409`).
- **email.py** — aiosmtplib + plantillas Jinja2; multi-proveedor (Brevo/Gmail/MailHog);
  best-effort.
- **errors.py** — `utcnow_naive()`, `internal_error()` (loguea real, responde 500
  genérico; `IntegrityError → 409`).

### Variables de entorno principales

`PROJECT_NAME`, `ENVIRONMENT`, `DEBUG`, `LOG_LEVEL`,
`POSTGRES_SERVER/USER/PASSWORD/DB/PORT` + pool (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
`DB_POOL_RECYCLE`), `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`,
`REFRESH_TOKEN_EXPIRE_DAYS`, `ACCOUNT_LOCKOUT_*`, `PASSWORD_RESET_*`,
`TWO_FACTOR_*` (incl. `TWO_FACTOR_REQUIRED_ROLES`), `PASSWORD_*` (política),
`BACKEND_CORS_ORIGINS`, `RATE_LIMIT_LOGIN`, `RATE_LIMIT_DEFAULT`,
`PAGINATION_MAX_LIMIT`, `REDIS_URL`, `AUTH_CACHE_TTL_SECONDS`,
`FIELD_ENCRYPTION_KEY`, `UPLOAD_DIR`, `MAX_UPLOAD_SIZE_MB`,
`ALLOWED_UPLOAD_EXTENSIONS`, `SMTP_*`, `EMAIL_ENABLED`.

## Migraciones (Alembic)

23 migraciones en `app/alembic/versions/` (head: `c7d8e9f0a1b2`,
`2026-06-05_config_color_fondo`). Se aplican solas en el arranque
(`alembic upgrade head`).

```bash
docker exec lombardi-backend-1 alembic current        # revisión actual
docker exec lombardi-backend-1 alembic history         # historial
docker exec lombardi-backend-1 alembic upgrade head    # aplicar
docker exec lombardi-backend-1 alembic downgrade -1     # revertir una
```

Hitos: modelo inicial, secuencias de códigos, índices, endurecimiento de integridad
(CHECKs, FKs ondelete, **índice único parcial de "movimiento abierto"**), token
revocado, account lockout, idempotencia, **auditoría append-only (trigger)**,
consumibles, adjuntos, compras, password reset, 2FA, color de fondo.

## Tests

24 archivos, **138 tests** (auth, 2FA + reset admin, RBAC boundaries, integridad,
transiciones de estado, exports, documentos, adjuntos, consumibles, compras/recepción,
offboarding, paginación, emails). Corren sobre SQLite en memoria.

```bash
docker exec lombardi-backend-1 python -m pytest tests/         # todos
docker exec lombardi-backend-1 python -m pytest tests/test_two_factor.py -v
docker exec lombardi-backend-1 python scripts/check_rbac.py    # guard RBAC
```

## Patrón de un endpoint (ejemplo)

```python
# endpoint (core.py): valida entrada + RBAC, delega al service
@router.post("/activos", response_model=ActivoResponse, status_code=201, dependencies=OPERATIVO)
async def create_activo(schema: ActivoCreate, request: Request, current_user: CurrentUser, ...):
    return await service.create_activo(schema, usuario_id=current_user.USU_Usuario)

# service (services/core.py): valida FKs/unicidad, audita, commit
async def create_activo(self, schema, usuario_id=None):
    ...                                  # validaciones de negocio
    nuevo = await self.repo.create_activo(schema)
    await self.gov_repo.create_audit_log("CREATE", "INV_ACTIVO", {...}, usuario_id=usuario_id)
    await self.db.commit()               # IntegrityError → 409 vía internal_error/commit_or_409
    return nuevo
```
