# Lombardi — Bitácora de avances 2026-05-26 a 2026-06-02

Sistema de inventario TI (FastAPI + React + Postgres + Redis + Caddy) llevado
desde un estado "funcional al 50%" hasta producción-ready con seguridad
endurecida, lógica de negocio coherente, notificaciones por email y **94 tests
automatizados verdes** (+ validación de los 155 endpoints, 0 errores 5xx).

> **¿Sesión nueva? Empieza por [§16 — Guía de onboarding](#16-guía-para-una-nueva-sesión-enfoque-y-continuaciones)**:
> resume el enfoque, la estructura, las convenciones y qué continuar.

> **Actualización 2026-06-01/02:** auditoría de seguridad e integridad a nivel
> enterprise — ver [§13](#13-auditoría-enterprise-y-endurecimiento-profundo-2026-06-0102).
> Se cerraron 2 vulnerabilidades (escalada de privilegios, 500 explotable), 1
> race de concurrencia, y se añadieron cookie HttpOnly, audit append-only,
> índices, y un pase de consistencia formal. Stack validado end-to-end en vivo.

> **Actualización 2026-06-03:** definición de roles desde el frontend con
> bitácora antes→después, y **3 módulos de negocio nuevos** (Consumibles,
> Adjuntos por activo, Compras/Proveedores/Garantías) — ver
> [§17](#17-roles-desde-el-frontend--3-módulos-nuevos-2026-06-03). Luego se
> **profesionalizaron** con automatización de lazo cerrado (recibir una orden
> suma stock y da de alta activos), alertas por email (stock bajo, garantías),
> factura adjunta a la orden, vistas de detalle e historial, y export CSV — ver
> [§17.7](#177-profesionalización-lazo-cerrado-y-automatización). Además:
> **restablecimiento de contraseña por email** (token de un solo uso al correo del
> usuario) y **garantía reforzada de "nunca sin super admin"** — ver
> [§17.9](#179-recuperación-de-cuenta-y-garantía-de-super-admin), más **aviso de
> seguridad al usuario** cuando su contraseña cambia y **throttle por cuenta** de
> los reset, y **2FA/MFA** (TOTP + Email-OTP + códigos de recuperación, obligatorio
> para roles admin) — ver [§17.10](#1710-2fa--mfa-totp--email-otp). Tests:
> **94 → 136 verdes**. Migraciones nuevas hasta `b6c7d8e9f0a1`. Validado
> end-to-end contra el stack real (RBAC, robustez, lazo cerrado, invariante de
> super admin y login 2FA en vivo, 0 errores 5xx).

---

## Índice rápido

| Día | Sección | Tema |
|---|---|---|
| 05-26 | [§1](#1-bloques-de-mejora-aplicados-y-validados-b1b6) | Hardening producción — Redis, paginación, tests CI, transactional, monitoring |
| 05-26 | [§2](#2-auditoría-de-seguridad--hallazgos-y-fixes) | Auditoría de seguridad — 12 hallazgos cerrados |
| 05-27 | [§3](#3-bugs-funcionales-detectados-y-resueltos) | Bug AssetsPage `limit=500` + estado `Asignado` vs `En Bodega` |
| 05-27 | [§4](#4-tests-unitarios-exhaustivos-60-51) | Tests unitarios por módulo |
| 05-28 | [§5](#5-validaciones-de-producción) | Backup→restore + flujos UI + production readiness |
| 05-28 | [§6](#6-auditoría-lógica-de-negocio--7-flujos) | Demo E2E 7 flujos + bug cierre mantenimiento |
| 05-29 | [§7](#7-notificaciones-por-email-smtp) | Sistema de emails SMTP multi-proveedor |
| 06-01 | [§8](#8-reply-to-dinámico--gmail-smtp) | Reply-To del operador + Gmail + firma "Ejecutado por" |
| — | [§9](#9-estado-actual-del-sistema) | Snapshot final del sistema |
| — | [§10](#10-credenciales-y-cómo-probar) | Credenciales + cómo probar |
| — | [§11](#11-commits-creados) | Lista de commits |
| — | [§12](#12-pendientes) | Qué falta para production real |
| 06-01/02 | [§13](#13-auditoría-enterprise-y-endurecimiento-profundo-2026-06-0102) | **Auditoría enterprise**: escalada de privilegios, cookie HttpOnly, audit append-only, concurrencia, índices, consistencia formal |
| 06-02 | [§14](#14-mejoras-funcionales-de-negocio-2026-06-02) | **Mejoras funcionales**: actas Word/PDF + descargo, características (RAM/disco/batería), reactivar, filtros, bitácora, hostname, dashboard, cascada, validación de endpoints |
| 06-02/03 | [§15](#15-documentos-corporativos-configuración-y-mensajero-2026-06-0203) | Actas al formato corporativo, encabezado configurable, mensajero externo, sin emojis |
| — | [§16](#16-guía-para-una-nueva-sesión-enfoque-y-continuaciones) | **Guía de onboarding**: enfoque, estructura, convenciones y continuaciones |
| 06-03 | [§17](#17-roles-desde-el-frontend--3-módulos-nuevos-2026-06-03) | **Roles desde el frontend** (gating + bitácora antes→después) y **3 módulos**: Consumibles, Adjuntos, Compras/Proveedores/Garantías |
| 06-05 | [§18](#18-endpoints-rbac-e-integridad-de-datos-2026-06-05) | **Endpoints/RBAC/integridad**: `commit_or_409` unificado, cotas Pydantic alineadas a BD, matriz RBAC + guard automatizado |
| 06-05 | [§19](#19-configuración-color-de-fondo-y-traducciones-completas-2026-06-05) | **Config/UI/i18n**: color de fondo configurable (migración `c7d8e9f0a1b2`), ConfigPage rediseñada, 255 traducciones EN/IT completadas (paridad 517) |

---

## 1. Bloques de mejora aplicados y validados (B1–B6)

### B1 — Redis para SlowAPI + caché de auth (ESC-1 / ESC-2)
- `app/core/cache.py` con cliente Redis async y helpers `cache_get/set/delete`.
- `app/api/deps.py::get_current_user` cachea por `jti` (TTL=30s). Invalidación
  inmediata en logout y password-change.
- SlowAPI usa Redis como storage compartido entre workers/réplicas.
- Servicio `redis:7-alpine` en compose con `--requirepass` (AUTH activo).
- **Validado**: tras 5 hits a `/me` → 1 sola entrada `auth:jti:*` en Redis.

### B2 — Paginación server-side + `/cat/modelos-flat`
- `app/schemas/common.py::PaginatedResponse[T]` (envoltorio
  `{items, total, page, per_page}`).
- `POST /core/activos/search` devuelve el envoltorio paginado.
- `GET /cat/modelos-flat` devuelve modelos con marca embebida en JOIN único
  → evita N+1 desde el frontend.

### B3 — Tests + CI
- `tests/test_auth_cache.py`, `test_pagination.py`, `test_health_metrics.py`.
- `.github/workflows/{backend,frontend}-ci.yml` (pytest + ruff + npm build).

### B4 — `@transactional` + `commit_or_409`
- `app/core/transactional.py`: decorador y helper.
- Migrados `catalogs/location/organization/maintenance` → IntegrityError → 409 unificado.

### B5 — Monitoring + backup off-site
- `/health/full` (DB + Redis) y `/metrics` Prometheus-style.
- `scripts/backup_db.sh`: opcional sync S3 (`BACKUP_S3_BUCKET`), verificación
  con `gzip -t`, `umask 077` + `chmod 700`.

### B6 — Incrementales
- Middleware `request_context` con `X-Request-ID` + `bind_contextvars`.
- `GET /gov/auditoria/resumen` agregado por acción/entidad.
- `Makefile` con targets `up/down/test/backup/restore/health/metrics`.

---

## 2. Auditoría de seguridad — hallazgos y fixes

Tres agentes en paralelo (rate-limit, SQL/queries, red).

### CRÍTICO — Bypass del rate-limit por X-Forwarded-For spoofable
**Diagnóstico**: nginx usaba `$proxy_add_x_forwarded_for` que ANEXA lo que
el cliente envíe. Atacante rotaba `X-Forwarded-For: a.b.c.d` y burlaba el
límite 5/min del login.

**Fix**:
- `nginx.conf`: `proxy_set_header X-Forwarded-For $remote_addr` (overwrite).
- `nginx.conf`: `proxy_set_header X-Real-IP $http_x_real_ip` (preserva la
  IP real que Caddy ya puso en el edge).
- `app/core/limiter.py::client_ip_key`: prefiere `X-Real-IP`, fallback al
  **último** hop de XFF, nunca el primero.

**Validado**: 5 intentos con `X-Forwarded-For: 88.88.88.{1..5}` siguen
disparando 429 al 5º.

### ALTO — Endpoints PII sin rate-limit
- `@limiter.limit("20/minute")` en `/org/personas*`, `/org/usuarios`.
- `@limiter.limit("10/minute")` en `/org/departamentos/{resumen,detalle}`,
  `/gov/auditoria/resumen`, `/login/logout`.
- `@limiter.limit("30/minute")` en `/gov/config`.

### ALTO — Redis sin AUTH
- `--requirepass ${REDIS_PASSWORD}` + `REDIS_URL=redis://:pwd@redis:6379/0`.
- Validador en `config.py` rechaza producción si `REDIS_URL` sin credenciales.

### ALTO — `SEED_DEMO=true` en producción
- `seed_demo.py` aborta con `SystemExit(1)` si `ENVIRONMENT=production`.
- `entrypoint.sh` aborta antes de invocar el seed.
- `FIELD_ENCRYPTION_KEY` obligatorio en prod (model_validator).

### MEDIO — Otros fixes
- `/me/password`: lockout por usuario (no solo `/login`).
- `q` filter: `max_length=64` + escape de `%` y `_` en ilike() para frenar
  LIKE leading-wildcard DoS.
- CORS `allow_credentials=False` (Bearer no requiere cookies).
- Permissions-Policy ampliada (interest-cohort, browsing-topics, usb, etc.).
- HSTS con `preload`.
- `security_opt: no-new-privileges:true` en todos los servicios.
- Backups: dumps con permisos 600 (umask 077).

### BAJO — Otros
- `Idempotency-Key` regex `^[A-Za-z0-9_-]{16,128}$`.
- `datetime.utcnow()` → helper `utcnow_naive()` en 7 archivos.
- `encrypt/decrypt_field` loguea warning estructurado.
- `.gitignore` frontend cubre `.env`.

---

## 3. Bugs funcionales detectados y resueltos

### Bug 1 — `AssetsPage` no cargaba data
**Causa real**: el frontend pedía `limit=500` pero el backend cota a
`PAGINATION_MAX_LIMIT=200`. Cada request devolvía `422 VALIDATION_ERROR`
y la tabla quedaba vacía sin mensaje al usuario.

**Fix**: `AssetsPage.tsx::loadData` → `getActivos(0, 200)`. Bundle nuevo
desplegado. El usuario solo recarga la página (no se cachea index.html).

### Bug 2 — Activo asignado mostraba estado "En Bodega"
**Causa**: `registrar_movimiento` creaba el movimiento pero NO actualizaba
`INV_ACTIVO.EOP_Estado_Operativo`. Solo `offboarding_persona` lo hacía.

**Fix** (`services/traceability.py`): helpers `_get_estado_id`,
`_set_activo_estado` y transición de estado según tipo de movimiento en la
**misma transacción** que crea el movimiento:
- Asignación / Préstamo → `Asignado`
- Devolución → `En Bodega`
- Ingreso → `Disponible`
- Transferencia → `Asignado` (idempotente)

### Bug 3 — `get_historial_activo` con MissingGreenlet
**Causa**: faltaba `selectinload(Movimiento.activo)`. Detectado por test
nuevo `test_historial_activo_incluye_movimientos_cerrados`.

**Fix**: `repositories/traceability.py` añade selectinload completo de
`Movimiento.activo.modelo.marca` y `.tipo_activo`.

---

## 4. Tests unitarios exhaustivos (60 → 71)

**Suite final**: 71 tests en 13 archivos, todos verdes.

| Archivo | Tests | Cubre |
|---|---|---|
| `test_auth.py` | 7 | login, password policy, lockout |
| `test_auth_cache.py` | 3 | logout/password-change revocan tokens |
| `test_health.py` | 1 | liveness |
| `test_health_metrics.py` | 2 | `/health/full`, `/metrics` |
| `test_pagination.py` | 3 | envoltorio paginado, `/cat/modelos-flat` |
| `test_state_transitions.py` | 7 | asignar→Asignado, devolver→Bodega, baja, préstamo, transfer, reasig |
| `test_assignments.py` | 5 | vigentes, historial, errores 400/404 |
| `test_offboarding.py` | 5 | libera activos, desactiva user+tokens, idempotente, último SA bloqueado |
| `test_consistency.py` | 5 | invariantes cross-módulo (1 mov abierto, BD↔estado, audit por op) |
| `test_exports.py` | 6 | CSV estructura, anti-injection, consistencia BD↔export |
| `test_security_boundaries.py` | 7 | 401 sin token, q max_length, escape LIKE, Idempotency regex |
| `test_software.py` | 5 | instalar/desinstalar uso, idempotency, cupo agotado |
| `test_maintenance.py` | 7 | crear ticket, 1-por-activo, detalle+cerrar, cierre respeta asignación |
| `test_email_notifications.py` | 8 | templates renderizan, subjects, autoescape XSS, admins, resiliencia |

**Bugs detectados por la suite y arreglados**:
1. `EOP_Estado` no transicionaba — cubierto ahora por `test_state_transitions` + `test_consistency`.
2. `get_historial_activo` con MissingGreenlet — cubierto por `test_assignments`.
3. Cierre de mantenimiento ignoraba asignación — cubierto por `test_maintenance::test_cerrar_mantenimiento_de_activo_asignado_lo_deja_asignado`.

---

## 5. Validaciones de producción

### Backup → restore E2E ✓
- Backup vía `scripts/backup_db.sh`: 16KB, gzip íntegro.
- Daño deliberado: -3 activos / -3 movimientos.
- Restore vía `gunzip | psql --set ON_ERROR_STOP=on`.
- Conteos coinciden con snapshot original (9/8/5/9/17/8).
- **Bug arreglado en scripts**: `source .env` rompía por valores con
  espacios. Reescrito con `_load_env_var()` + `|| true` para set -e safe.

### Flujos UI probados via API ✓
12 endpoints UI no probados previamente: `/trazabilidad/persona/*/asignaciones`,
`/org/departamentos/*/detalle`, `/soft/*`, `/mantenimiento/*`,
`/gov/auditoria/*`, `/export/*`, `/trazabilidad/acta/*` (Word .docx 37KB).

### Production readiness ✓
| Check | Resultado |
|---|---|
| HTTP→HTTPS redirect (Caddy) | 308 con `Location: https://...` ✓ |
| Security headers | HSTS preload, CSP estricta, Permissions-Policy ampliada, X-Frame DENY ✓ |
| Sourcemaps en bundle | **0** archivos `.map` (bundle prod 885KB) ✓ |
| Validador `FIELD_ENCRYPTION_KEY` | Aborta arranque en prod con mensaje claro ✓ |
| `/metrics` | Documentado: red Docker interna lo expone vía Caddy. Sólo 3 gauges, sin PII. |

---

## 6. Auditoría lógica de negocio — 7 flujos

### Estados operativos del sistema

| ID | Estado | Cuándo aplica |
|---|---|---|
| 1 | Disponible | Recién creado, sin uso registrado |
| 2 | Asignado | Hay `INV_MOVIMIENTO` abierto con una persona |
| 3 | En Reparación | Hay `INV_MANTENIMIENTO` abierto |
| 4 | Baja | Soft delete (DELETE_LOGIC) |
| 5 | En Bodega | Devuelto a inventario |

### Demo E2E ejecutada (script `scripts/demo_flujos.sh`)

```
── Estado inicial ──     PC00002 | En Bodega    | sin asignación
── 1. ASIGNACIÓN ──      PC00002 | Asignado     | Sofia Cruz
── 2. TRANSFERENCIA ──   PC00002 | Asignado     | Pedro Vasquez
── 3. APERTURA MANT ──   PC00002 | En Reparación| Pedro Vasquez | ticket abierto
── 4. CIERRE MANT ──     PC00002 | Asignado     | Pedro Vasquez   ← FIX aplicado
── 5. DEVOLUCIÓN ──      PC00002 | En Bodega    | sin asignación
── 6. BAJA LÓGICA ──     PC00002 | Baja         | sin asignación
── 7. Reasignar baja ──  400 CANNOT_ASSIGN_DECOMMISSIONED_ASSET
```

### Bug arreglado durante el audit

**Bug**: `cerrar_mantenimiento` forzaba `EOP_Estado='Disponible'` sin
verificar si había movimiento abierto. Si Pedro tenía el activo y abrías
+ cerrabas un ticket → quedaba `Disponible | Pedro Vasquez` (inconsistente).

**Fix** (`services/maintenance.py::cerrar_mantenimiento`):
- Hay movimiento abierto → estado `Asignado`
- No hay movimiento → estado `En Bodega`
- En la **misma transacción** que el cierre del ticket.

### Garantías de negocio validadas

1. **Máx 1 movimiento abierto por activo** (UNIQUE parcial + lock pessimista).
2. **Máx 1 ticket de mantenimiento abierto por activo** (validación en service).
3. **Activo con movimiento abierto ⇒ estado ∈ {Asignado, En Reparación}**.
4. **DELETE rechaza si hay movimiento abierto** (400 `CANNOT_DELETE_ASSIGNED_ASSET_RETURN_IT_FIRST`).
5. **Activo en Baja no se asigna** (400 `CANNOT_ASSIGN_DECOMMISSIONED_ASSET`).
6. **Offboarding atómico**: cierra movimientos + Bodega + desactiva usuario + revoca tokens + audita.

---

## 7. Notificaciones por email SMTP

Sistema de notificaciones automáticas integrado en cada evento del ciclo
de vida de un activo. SMTP estándar (`aiosmtplib`) → portable a cualquier
proveedor con free tier.

### Proveedores gratis compatibles

| Proveedor | Free tier | Host SMTP |
|---|---|---|
| Brevo (ex-Sendinblue) | **300/día forever** | smtp-relay.brevo.com:587 |
| SendGrid | 100/día forever | smtp.sendgrid.net:587 |
| Resend | 100/día + 3K/mes | smtp.resend.com:465 |
| MailerSend | 3K/mes | smtp.mailersend.net:587 |
| Gmail | 500/día | smtp.gmail.com:587 (con App Password) |
| Google Workspace | 2,000/día/cuenta ($6/mes) | smtp.gmail.com:587 |
| MailHog | local dev | mailhog:1025 |

### 7 eventos generan email automáticamente

| Evento | Template | Destinatarios |
|---|---|---|
| Asignación | `asignacion` | Persona asignada + admins |
| Devolución | `devolucion` | Persona que devolvió + admins |
| Transferencia | `transferencia` | Origen + Destino + admins |
| Baja lógica | `baja` | Solo admins |
| Offboarding | `offboarding` | Solo admins (con lista de activos liberados) |
| Apertura mantenimiento | `mantenimiento_abierto` | Solicitante + admins |
| Cierre mantenimiento | `mantenimiento_cerrado` | Solo admins |

### Garantías técnicas

- **Post-commit + fire-and-forget**: `asyncio.create_task` desacopla el SMTP.
  Si el envío falla, la operación de negocio NO se revierte.
- **Kill switch**: `EMAIL_ENABLED=false` o `SMTP_HOST` vacío → silenciar.
- **Anti-XSS**: Jinja2 con `autoescape=True`.
- **MailHog para dev**: `docker compose --profile dev up -d mailhog`
  → UI en `http://localhost:8025`.

---

## 8. Reply-To dinámico + Gmail SMTP

Cada email identifica **quién ejecutó la acción** (técnico, admin, etc.),
no solo el evento.

### Cambios

**`app/core/email.py`**:
- `send_notification(..., reply_to, operator_name, operator_role)`.
- Header SMTP **`Reply-To`** = email del operador → cuando un destinatario
  responde, el correo va al técnico/admin que ejecutó, NO al noreply.
- Bloque visual nuevo en cada template:
  ```
  Ejecutado por: Ana Torres (TECNICO)
  Contacto:      atorres@lombardi.demo
  ```

**`app/services/traceability.py`**: helper `_operator_info(usuario_id)`
que dado el UUID del usuario que ejecutó devuelve `(nombre, rol, email)`.
Usado en asignación, devolución, transferencia, offboarding.

**`app/services/core.py`** (baja) y **`maintenance.py`** (apertura/cierre):
mismo enriquecimiento inline.

### Validación E2E con MailHog

**`sa` (SUPER_ADMIN) asigna PC00002**:
```
Subject:  [Inventario] Activo asignado: PC00002
To:       scruz@lombardi.demo, admin.ti@lombardi.group
Reply-To: admin@inventarioti.example.com
Body:     Ejecutado por: System Administrator (SUPER_ADMIN)
```

**`atorres` (TECNICO) asigna PC00002**:
```
Subject:  [Inventario] Activo asignado: PC00002
To:       scruz@lombardi.demo, admin.ti@lombardi.group
Reply-To: atorres@lombardi.demo
Body:     Ejecutado por: Ana Torres (TECNICO)
```

### Setup Gmail (en `.env`)

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_TLS=false
SMTP_USER=notificaciones.lombardi@gmail.com
SMTP_PASSWORD=xxxx_xxxx_xxxx_xxxx        # App Password de 16 chars
SMTP_FROM_EMAIL=notificaciones.lombardi@gmail.com
SMTP_FROM_NAME=Sistema Inventario Lombardi
NOTIFY_ADMIN_EMAILS=admin.ti@lombardi.group,otro@lombardi.group
EMAIL_ENABLED=true
```

**Pasos**:
1. Login Gmail destino → activar 2-Step Verification.
2. https://myaccount.google.com/apppasswords → crear "Mail / Other (Lombardi)".
3. Copiar 16 chars al `SMTP_PASSWORD`.
4. `docker compose up -d --force-recreate backend`.

### Sobre dominios formales `@lombardi.group`

| Modo | Costo | Dominio formal en `From:` |
|---|---|---|
| Gmail personal | gratis | ❌ aparece "via gmail.com" en clientes estrictos |
| Gmail "Send mail as" + dominio propio | gratis | ⚠️ requiere DNS, ainda con "via gmail.com" |
| **Google Workspace** | $6/mes/cuenta | ✅ nativo, 2000/día |
| **Brevo con dominio verificado** | gratis 300/día | ✅ totalmente, 3 registros DNS |

**Recomendación**: Workspace si lo tienen, Brevo si no.

---

## 9. Estado actual del sistema

### Stack desplegado
```
backend   ✓ FastAPI 4 workers, gunicorn, sin sourcemap
caddy     ✓ TLS edge (Let's Encrypt automático con DOMAIN real)
db        ✓ Postgres 16 alpine, security_opt
frontend  ✓ nginx + bundle prod (885KB) sin .map
redis     ✓ Redis 7 alpine, AUTH habilitado
mailhog   profile dev (solo `--profile dev`)
```

### Cobertura

| Métrica | Valor |
|---|---|
| **Tests automatizados** | 71/71 verdes (~30s) |
| **Endpoints con rate-limit explícito** | 9 (login, logout, password, personas, usuarios, departamentos, auditoría, config, search) |
| **Eventos con email automático** | 7 (asignar, devolver, transferir, baja, offboarding, mant abierto, mant cerrado) |
| **Templates de email** | 7 con autoescape XSS |
| **Garantías de invariante validadas** | 6 (movimiento único, estado coherente, baja segura, etc.) |
| **Scripts operacionales** | backup_db.sh, restore_db.sh, purge_security.sh, demo_flujos.sh, init_prod.py, seed_demo.py |

### Datos demo cargados
```
Activos:        9 (LPT00001-05, PC00001-02, MON00001, MSE00001)
Personas:       8 activas
Usuarios:       5 (SUPER_ADMIN, ADMIN_TI, TECNICO×2, CONSULTA)
Movimientos:    movimientos vigentes coherentes con estado
Catálogos:      8 marcas, 8 modelos, 5 estados, 5 tipos mov, 3 tipos mant
Software:       4 software + 3 licencias
Auditoría:      ≥17 eventos forenses
```

### Invariante BD (debe devolver 0)
```sql
SELECT COUNT(*) FROM "INV_ACTIVO" a
JOIN "INV_MOVIMIENTO" m ON m."ACT_Activo"=a."ACT_Activo"
                       AND m."MOV_Fecha_Devolucion" IS NULL
JOIN "INV_ESTADO_OPERATIVO" e ON e."EOP_Estado_Operativo"=a."EOP_Estado_Operativo"
WHERE e."EOP_Nombre" IN ('Disponible', 'En Bodega', 'Baja');
-- → 0 ✓
```

---

## 10. Credenciales y cómo probar

### URLs
- **Frontend**: https://localhost (Caddy con cert autofirmado en dev)
- **API directa**: https://localhost/api/v1
- **Swagger**: https://localhost/api/v1/docs
- **MailHog UI** (dev): http://localhost:8025
- **Health**: https://localhost/health/full

### Usuarios

| Username | Password | Rol | Notas |
|---|---|---|---|
| `sa` | `JMpEAgfwlPWLixpmzkSvCrFgA0c` | SUPER_ADMIN | Bootstrap |
| `jramirez` | `Lombardi#2026` | ADMIN_TI | |
| `atorres` | `Lombardi#2026` | TECNICO | |
| `mgarcia` | `Lombardi#2026` | CONSULTA | |
| `cmendez` | `Lombardi#2026` | TECNICO | Útil para probar offboarding |

### Comandos clave

```bash
# Tests
docker exec lombardi-backend-1 python -m pytest tests/ -v   # 71/71

# Demo E2E de los 7 flujos de negocio
bash scripts/demo_flujos.sh

# MailHog para inspeccionar emails (dev)
docker compose --profile dev up -d mailhog
# UI: http://localhost:8025

# Backup
bash scripts/backup_db.sh

# Métricas (interno)
docker exec lombardi-backend-1 curl -s http://127.0.0.1:8000/metrics
```

### Cómo probar offboarding desde la UI

1. Login con `sa` / `JMpEAgfwlPWLixpmzkSvCrFgA0c`.
2. `ORGANIZATION → Personas` → Carlos Mendez → "Ver detalle".
3. Confirmar: 3 activos asignados + usuario `cmendez` vinculado.
4. Click **"Offboarding"**, ingresa motivo, confirma.
5. Validar:
   - `OPERATIONS → Activos`: LPT00001 + MON00001 + MSE00001 en "En Bodega".
   - `ADMIN → Auditoría`: evento `OFFBOARDING` con snapshot completo.
   - Login `cmendez` / `Lombardi#2026` → `INACTIVE_USER`.
   - **Email en MailHog**: notificación a admins con lista de activos liberados.

---

## 11. Commits creados

### Repo `backend/inventarioTI-backend`

| Hash | Tema |
|---|---|
| 78fc42a | Production hardening (B1-B6) |
| 47f2c0f | Cierre hallazgos auditoría (XFF, rate-limit, Redis AUTH) |
| 84f85ec | Hardening final: deprecaciones, helper utcnow |
| 6f8de64 | Tests software + maintenance (9 tests) |
| (varios) | Fix transición EOP_Estado, fix cierre mantenimiento, etc. |
| (último) | Email Reply-To dinámico + Gmail SMTP setup |

### Repo `backend/inventarioTI-frontend`

| Hash | Tema |
|---|---|
| 5605d70 | CRUD completo, paginación, dialogs MUI |
| d256ed7 | nginx X-Forwarded-For anti-spoof |
| d00e847 | .gitignore .env defensa |
| b645c3d | Fix X-Real-IP + AssetsPage resiliente |
| (último) | AssetsPage limit=500 → 200 |

### Scripts (fuera de repo git)

- `scripts/backup_db.sh` + `restore_db.sh`: fix parse `.env` con espacios.
- `scripts/demo_flujos.sh`: demo E2E de los 7 flujos de negocio.

---

## 12. Pendientes

### Para production real

| # | Pendiente | Notas |
|---|---|---|
| 1 | Probar deploy con `DOMAIN=tu-dominio.com` y Let's Encrypt real | Caddy emite cert automáticamente; nunca probado fuera de localhost |
| 2 | Rotar TODOS los secrets del `.env` demo | `JMpEAgfwlPWLixpmzkSvCrFgA0c`, `Lombardi#2026`, `FIELD_ENCRYPTION_KEY` |
| 3 | Configurar SMTP real (Gmail App Password o Brevo) | Setup documentado en §8 |
| 4 | Migraciones desde producción existente | Probar `alembic upgrade head` con datos reales antes del cutover |

### Mejoras nice-to-have

- **Tests frontend con Vitest** (cobertura actual: 0).
- **Tests E2E con Playwright/Cypress** — capturaría el bug `limit=500` automáticamente.
- **`/metrics` con autenticación** (basic_auth en Caddy).
- **Retención de audit log** — política y purga ≥ 90 días.
- **Alerting** sobre `/metrics` (Prometheus + Alertmanager).
- ~~**Aplicar `@transactional`** a `software.py` y `traceability.py` (aún usan try/except viejo).~~
  **Hecho 2026-06-05** (vía `commit_or_409`, ver [§18](#18-endpoints-rbac-e-integridad-de-datos-2026-06-05)).

### Asumido sin cerrar

| Riesgo | Mitigación actual | Lo que falta |
|---|---|---|
| Demo users con password `Lombardi#2026` conocida | Solo dev/demo | Cambiar al desplegar |
| `.env` con secrets en repo local | `.gitignore` lo cubre | Mover a Vault / SOPS / docker secrets |
| Frontend bundle sin sourcemap-strip explícito | Vite default | Confirmar en build prod |
| `/metrics` accesible vía red interna Docker | Documentado | basic_auth en Caddy si se quiere ocultar |

---

## Apéndice — Comandos de diagnóstico rápido

```bash
# Estado del stack
docker compose ps

# Logs backend en vivo
docker compose logs -f backend

# Suite completa de tests
docker exec lombardi-backend-1 python -m pytest tests/

# Reparar invariante BD (caso histórico, NO debería ser necesario)
docker compose exec db psql -U invuser -d inventario -c "
  UPDATE \"INV_ACTIVO\" a SET \"EOP_Estado_Operativo\"=2
  WHERE a.\"ACT_Activo\" IN (
    SELECT \"ACT_Activo\" FROM \"INV_MOVIMIENTO\" WHERE \"MOV_Fecha_Devolucion\" IS NULL
  ) AND a.\"EOP_Estado_Operativo\" NOT IN (2, 3);"

# Limpiar caché Redis (resetea contadores rate-limit + auth cache)
docker compose exec redis sh -c 'redis-cli -a $REDIS_PASSWORD --no-auth-warning FLUSHDB'

# Probar SMTP sin tocar negocio
docker compose --profile dev up -d mailhog
# luego cualquier asignación dispara un email visible en localhost:8025
```

---

## 13. Auditoría enterprise y endurecimiento profundo (2026-06-01/02)

Auditoría de seguridad e integridad a nivel enterprise, validada **end-to-end
contra el stack real** (no solo tests). Tests: **71 → 83 verdes**. Migraciones
nuevas: `2025-12-13_auditoria_append_only`, `2025-12-14_concurrency_query_indexes`.

### 13.1 Seguridad (ronda 1)
- **Secretos**: `SECRET_KEY` rotado; `FIELD_ENCRYPTION_KEY` soporta rotación sin
  downtime vía `MultiFernet` (lista por comas, primaria cifra / legadas descifran);
  descifrado **falla cerrado** en producción ante token inválido. Runbook nuevo
  **`SECURITY.md`** con la rotación de DB/Redis/admin (no automatizable a ciegas).
- **Audit forense append-only**: trigger Postgres que rechaza `UPDATE`/`DELETE`
  sobre `INV_AUDITORIA_SISTEMA` (validado: ambos → ERROR a nivel BD). Se auditan
  ahora `LOGIN_SUCCESS/FAILED`, `ACCOUNT_LOCKED`, `LOGOUT` con IP real + User-Agent.
- **Integridad de estado fail-closed**: si falta un estado canónico, la transacción
  **revierte** (antes: corrupción silenciosa) en asignación/devolución/transferencia/
  offboarding/mantenimiento.
- **Anti-enumeración de usuarios**: hash dummy (timing constante) + respuesta uniforme.
- **Cadena de suministro**: `python-jose>=3.4.0` (sobre CVEs), `cryptography>=43`, `pip-audit`.
- **Infra**: límites `mem/cpus/pids` en todos los servicios, `cap_drop: ALL` en backend,
  `/metrics` y `/health/full` bloqueados en el edge (Caddy 403; scraping interno intacto).

### 13.2 Sesión — refresh token en cookie HttpOnly
- El refresh token vive en cookie **HttpOnly + Secure + SameSite=Strict**
  (`Path=/api/v1/login`), inaccesible desde JS (inmune a exfiltración XSS).
- **Rotación + detección de reuso**: cada refresh revoca el jti usado; reusar el
  viejo → 401 `TOKEN_REVOKED` (validado en vivo). El body sigue disponible para
  clientes API. Frontend (`axios`/`AuthContext`/`authService`) ya no guarda el
  refresh en `sessionStorage`; hidrata vía cookie.

### 13.3 Protección de catálogo de sistema + cifrado de backups
- `EstadoOperativo` canónicos (Disponible/Asignado/En Reparación/Baja/En Bodega)
  **no se pueden renombrar/borrar** (409) — protegen la máquina de estados.
- `scripts/backup_db.sh`: cifrado opcional con `age` (`BACKUP_AGE_RECIPIENT`),
  *fail-closed* si se pide cifrado sin `age`.

### 13.4 Auditoría endpoint por endpoint (156 endpoints)
RBAC verificado en vivo (CONSULTA bloqueado en toda escritura, lecturas OK).
Dos vulnerabilidades reales encontradas, corregidas y re-validadas en vivo:
- **🔴 CRÍTICO — Escalada de privilegios** (`PATCH /org/usuarios/{id}`): validaba el
  rol *actual* del target pero no el rol *nuevo* → un `ADMIN_TI` podía elevar un
  `CONSULTA` a `SUPER_ADMIN`. **Fix**: solo `SUPER_ADMIN` otorga roles admin
  (`ONLY_SUPER_ADMIN_CAN_GRANT_ADMIN_ROLES`). Exploit confirmado y luego bloqueado.
- **🟠 ALTO — 500 explotable**: `app/services/catalogs.py` usaba `except IntegrityError`
  **sin importarlo** → borrar catálogo en uso lanzaba `NameError` → 500. **Fix**: import
  → ahora 409 `CANNOT_DELETE_BRAND_IN_USE`.

### 13.5 Concurrencia, consultas y transacciones
- **Race del mantenimiento único** (TOCTOU): la invariante "1 ticket abierto por
  activo" dependía solo de un SELECT. **Fix**: índice **único parcial**
  `uq_mantenimiento_activo_abierto` (espejo del de movimiento). `IntegrityError`→409
  en creación de movimiento y mantenimiento (antes 500 bajo concurrencia).
- **Índices** (drift modelo↔BD corregido): `ix_movimiento_activo`,
  `ix_mantenimiento_activo`, `ix_movimiento_persona`, `ix_movimiento_area`.
- **Secuencia race-safe**: `get_next_code` usa `INSERT ... ON CONFLICT DO NOTHING`
  + `FOR UPDATE` (validado: códigos secuenciales y únicos).

### 13.6 Pase de consistencia formal
- `_operator_info`: 2 queries → **1 JOIN**.
- **`internal_error` mapea cualquier `IntegrityError` a 409** (nunca 500) — consistencia
  DRY sin migrar a `@transactional` (incompatible con el patrón post-commit de emails).
- Política de contraseña **única fuente de verdad** (se quitó el `min_length` duplicado del Body).
- Actas Word restringidas a `OPERATIVO+` (contenían PII, eran AUTH-any).
- Tests con SQLite ahora aplican **FK enforcement** (`PRAGMA foreign_keys=ON`).

### 13.7 Exportación con formato profesional
- CSV con **BOM UTF-8** (Excel muestra acentos/ñ correctamente) y fechas legibles
  `YYYY-MM-DD HH:MM:SS` (sin la `T` ISO ni microsegundos). Anti-CSV-injection intacto.
- Acta de entrega Word (.docx) validada: empresa, fecha, colaborador, tabla de activos.

### 13.8 Correos validados end-to-end (MailHog)
Pipeline confirmado: HTML multipart, **Reply-To del operador**, bloque "Ejecutado
por", autoescape XSS (`<script>`→`&lt;script&gt;`), destinatarios = persona + admins.
Con un App Password real de Gmail entrega a bandejas reales sin más cambios.

### 13.9 Pendientes que quedan (operativos)
1. Configurar `SMTP_PASSWORD` con App Password real de Gmail (o `SMTP_HOST=mailhog` en dev).
2. Rotar `POSTGRES_PASSWORD` / `REDIS_PASSWORD` / admin según `SECURITY.md`.
3. Mover secretos a un gestor (Docker secrets / SOPS+age / Vault).
4. Definir `BACKUP_AGE_RECIPIENT` para activar el cifrado de backups.

---

## 14. Mejoras funcionales de negocio (2026-06-02)

Bloque de features pedidas por el usuario, todas desplegadas y validadas contra
el stack real. Tests: **93 verdes**. Migraciones nuevas:
`2025-12-15_spec_types_bateria`, `2025-12-16_modelo_tipo_activo`.

### 14.1 Documentos: actas Word + PDF con logo + hoja de descargo
- `services/documents.py` reescrito: arquitectura datos→render(docx|pdf). Encabezado
  con **logo de empresa embebido y justificado** (descargado de `SYS_Logo_URL`), banda
  con el color de marca, tabla estilizada y firmas. Degrada con elegancia si el logo falla.
- **PDF** nuevo vía `reportlab` (+`pillow`). Endpoints `/trazabilidad/acta/*` aceptan
  `?formato=pdf|docx` y `?tipo=entrega|descargo`.
- **Hoja de descargo** (devolución): mismo diseño con firmas invertidas ("la empresa
  RECIBE CONFORME"). En Movimientos aparece como ícono ámbar solo en movimientos ya
  devueltos. CSV de exportación ya llevaban BOM UTF-8 + fechas legibles (§13.7).

### 14.2 Características del equipo (RAM, disco, batería…)
- CRUD de especificaciones por activo: `GET/POST /core/activos/{id}/especificaciones`,
  `PATCH/DELETE /core/especificaciones/{id}` (auditado, 409 si se repite el tipo).
- Migración que añadió tipos faltantes (Batería, Salud de batería, MAC, IMEI…).
- UI en **Activos → Ver detalle → Información → "Características del equipo"**: chips
  editables + alta rápida. Los equipos ya tenían RAM/disco/CPU/SO del seed; ahora se ven.

### 14.3 Reactivar empleado / usuario
- **Empleado**: botón verde (recontratación) en personas inactivas → `PER_Estado=true`.
- **Usuario (login)**: switch en **ADMIN → Usuarios** → `USU_Estado=true`.

### 14.4 Offboarding más visible
- Botón "Dar salida / Descargo de activos" dentro del **detalle del empleado** (donde se
  ven sus activos), además del ícono de salida en la fila. Devuelve TODO a bodega +
  desactiva usuario, atómico.

### 14.5 Filtros y bitácora
- **Activos**: filtros por **estado** y por **tipo de componente** (con conteo), chips de
  estado con color (Baja en rojo). Así se ven los activos en bodega y los dados de baja.
- **Movimientos**: filtros por **tipo** (entrada/salida) y por **estado** (vigente/cerrado).
  Las bajas se ven en **ADMIN → Auditoría** (acción `DELETE` sobre activos).

### 14.6 Hostname al reasignar
- `MovimientoCreate.ACT_Hostname` opcional; `registrar_movimiento` actualiza el hostname
  del activo si se envía (conserva el actual si no). El `AssignmentDialog` precarga el
  hostname actual y permite cambiarlo para el nuevo usuario/equipo.

### 14.7 Dashboard accionable
- `services/stats.py` enriquecido: por estado/tipo/departamento, **garantías por vencer
  (90 días) y vencidas**, valor del inventario, costo de mantenimiento, licencias por
  agotarse, disponibles en bodega, en reparación, en baja.
- `DashboardPage` rediseñado con alertas, KPIs, distribuciones (barras) y listas accionables.

### 14.8 Cascada Modelo ↔ Tipo de componente
- Migración: columna `TAC_Tipo_Activo` (nullable) en `INV_MODELO`. `modelos-flat` acepta
  `?tipo_id=` (devuelve modelos de ese tipo + los sin tipo).
- **Modelos**: campo "Tipo de componente". **Crear activo**: al elegir el tipo, el
  desplegable de modelo muestra solo modelos de ese tipo (cascada "elijo Mouse → solo mouse").

### 14.9 Higiene
- **Erradicado `lombardi.group`** del `.env` (destinatarios → `example.com`, RFC 2606);
  0 referencias en repo/BD/logs. Ninguna prueba puede ir a ese dominio.

### 14.10 Validación integral de endpoints + fix de robustez
- Validación sistemática de **155 endpoints** contra el stack real (introspección de
  rutas + llamadas con auth): lecturas→200, mutaciones con body vacío→422, IDs
  inexistentes→404. Resultado: **0 errores 5xx**, 0 excepciones de conexión.
- **Bug encontrado y corregido**: `PATCH /org/usuarios/{id}` con body vacío generaba
  `UPDATE … SET  WHERE …` (SQL inválido) → 500. `UsuarioRepository.update` no protegía
  contra datos vacíos (los demás repos sí). Fix: guard `if update_data:` → no-op 200.
  Test de regresión `test_patch_usuario_empty_body_is_noop_not_500`.

---

## 15. Documentos corporativos, configuración y mensajero (2026-06-02/03)

Migraciones: `2025-12-17_config_acta_fields`. Tests: **94 verdes**.

### 15.1 Actas (Word + PDF) reescritas al formato corporativo de referencia
Tras analizar `ejemplo.pdf`, `services/documents.py` reproduce ese formato exacto:
- **Encabezado**: logo (izq) + código de formulario y "Ciudad, fecha larga en español" (der).
- **Título** centrado en negrita: `NOTA: ENTREGA DE EQUIPO` / `NOTA: DEVOLUCIÓN A {EMPRESA}`.
- **Tabla** `DISPOSITIVO | MARCA | MODELO | SERIE` con cabecera navy (`#1F3A5F`), texto
  blanco. `DISPOSITIVO` = hostname (o tipo, o código).
- **Cuerpo**: párrafo de casuísticas + `Descripción: {motivo}`.
- **Firmas**: dos columnas (izq colaborador "Entrega/Recibe equipo", der "Departamento de TI").
- **Pie**: texto legal en letra pequeña con viñeta.
- Arquitectura: `_gather()` (datos) → `_render_docx()` / `_render_pdf()` comparten estructura.
  `_ACTA_TEXTS` parametriza entrega vs descargo. Degrada con elegancia si el logo falla.

### 15.2 Encabezado del acta configurable
- `SYS_Codigo_Formulario` y `SYS_Ciudad` añadidos a `SYS_CONFIGURACION` (antes constantes).
- UI en **ADMIN → Configuración → "Datos del encabezado de las actas"**.

### 15.3 Mensajero externo (no pertenece a la empresa)
- Los endpoints de acta aceptan `?mensajero=Nombre`. Si se indica, la firma derecha muestra
  al **mensajero externo** ("Mensajero externo · No pertenece a {empresa}") en lugar del
  Departamento de TI — cubre el caso de un courier que recibe/transporta el equipo.
- UI: el botón de descargo en Movimientos abre un diálogo (`ActaDescargoDialog`) con
  formato (PDF/Word) + nombre opcional del mensajero.

### 15.4 Emojis eliminados de la interfaz
- Dashboard (`⚠️`, `🔑`) y plantillas de email (`📦 ↩️ 🔄 🗑️ 🚪 🔧 ✅`) → texto limpio.
  Verificado: 0 emojis en `frontend/src` y en `core/email.py`.

---

## 16. Guía para una nueva sesión (enfoque y continuaciones)

> Léeme primero si retomas el proyecto. Resume cómo está pensado, cómo trabajar y qué falta.

### 16.1 Qué es y dónde está
Inventario TI: **FastAPI + React/TS (Vite/MUI) + Postgres + Redis + Caddy**, en Docker.
- Monorepo en `C:\Lombardi`. Backend en `backend/inventarioTI-backend`, frontend en
  `backend/inventarioTI-frontend`. Orquesta `docker-compose.yml` (+ `Caddyfile`).
- **Backend en 4 capas**: `endpoint → service → repository → DB`. Regla de oro:
  *repositories solo `flush()`, services deciden `commit/rollback`*. Modelos `INV_*`/`SYS_*`
  con prefijo por columna (`ACT_`, `MOV_`, `EOP_`…).
- **Frontend por features**: `src/features/<x>/` = `XPage.tsx` + `XDialog.tsx` + `xService.ts`.
  Auth con access token en memoria + refresh en **cookie HttpOnly** (rotación + reuso → 401).

### 16.2 Cómo levantar, probar y reconstruir
```bash
# Tests backend (SQLite en memoria, sin Docker) — 94 verdes
cd backend/inventarioTI-backend && python -m pytest tests/
# Levantar/recrear todo (datos se preservan en volúmenes)
docker compose up -d --build
# Reconstruir solo backend o frontend tras un cambio
docker compose up -d --build backend   # o: frontend
# UI: https://localhost  (cert autofirmado) — sa / JMpEAgfwlPWLixpmzkSvCrFgA0c
# MailHog (dev): docker compose --profile dev up -d mailhog  + SMTP_HOST=mailhog
```
Migración de cabecera actual: **`b6c7d8e9f0a1`** (corre sola en el arranque vía `entrypoint.sh`).
Tests: **136 verdes** (`pytest`, SQLite en memoria). Dependencias nuevas (2026-06-03):
`pyotp`, `qrcode` (2FA); `pillow`/`reportlab` (PDF) ya estaban.

**Cómo probar emails/2FA sin Gmail real:** el stack arranca **sin `SMTP_HOST`**, así
que los correos (reset, avisos de cambio, alertas, **Email-OTP de 2FA**) se loguean
pero NO se entregan. Para verlos: `docker compose --profile dev up -d mailhog`, poner
`SMTP_HOST=mailhog` (env del backend) y recrear el backend → buzón web en
`http://localhost:8025`. **TOTP funciona sin SMTP** (offline): se prueba en
`UI → escudo del sidebar → App autenticadora → escanear QR con Microsoft/Google
Authenticator`. La URI TOTP es estándar RFC 6238 (SHA1/6díg/30s) → compatible con
todas las apps. Demo: `sa` se dejó **sin 2FA** (login solo-contraseña).

### 16.3 Convenciones a respetar (no romper)
- **RBAC en el backend** por endpoint (`require_admin/operativo/super_admin`); el frontend
  no es la fuente de verdad. Solo `SUPER_ADMIN` otorga roles admin (anti-escalada en create **y** update).
- **`internal_error()`** mapea cualquier `IntegrityError` a **409** (nunca 500). Úsalo en services.
- **Estados fail-closed**: si falta un `EstadoOperativo` canónico, la transacción revierte
  (no se corrompe el estado). Los estados/tipos "del sistema" no se pueden renombrar/borrar.
- **Invariantes con índice único parcial** (movimiento/mantenimiento abiertos) + lock; el índice
  es el backstop real, no solo el SELECT.
- **Auditoría append-only** (trigger Postgres): no hacer `UPDATE/DELETE` sobre `INV_AUDITORIA_SISTEMA`.
- **Emails post-commit fire-and-forget**: por eso `traceability/maintenance` NO usan `@transactional`
  (commitearía antes del email). No migrarlos a ciegas.
- **Documentos**: para cambiar el acta, editar `_ACTA_TEXTS` + `_gather` + los dos renderers
  (docx/pdf comparten estructura). El logo viene de `SYS_Logo_URL`.
- **Migraciones**: encadenar `down_revision` a la cabeza actual; guardar trigger/índices
  específicos de Postgres tras `if bind.dialect.name == "postgresql"`.
- **Tests con SQLite** tienen FK + UNIQUE activados (`PRAGMA foreign_keys=ON`). Cuidado: el
  email de personas seed usa `@test.local` (rechazado por `EmailStr`) → al crear usuarios en
  tests usar personas con email `@example.com`.

**Convenciones añadidas 2026-06-03 (sesión de seguridad + módulos):**
- **Nunca sin SUPER_ADMIN**: `update_usuario` y `offboarding_persona` bloquean degradar/
  desactivar al último super admin activo (`CANNOT_DISABLE_LAST_SUPER_ADMIN` /
  `CANNOT_OFFBOARD_LAST_SUPER_ADMIN`). No quitar esos chequeos. (El agujero histórico fue un
  usuario títere SUPER_ADMIN extra; mantener la tabla de usuarios limpia.)
- **2FA**: secreto TOTP cifrado con Fernet; OTP de email y códigos de recuperación solo como
  hash SHA-256. `TWO_FACTOR_REQUIRED_ROLES` (default `SUPER_ADMIN,ADMIN_TI`) no pueden
  desactivar su 2FA. Login en 2 pasos: `/login/access-token` devuelve `requires_2fa`+challenge
  si el usuario tiene 2FA; los tokens salen recién en `/login/2fa/verify`.
- **Reset/avisos**: `/login/password-reset/*` es **anti-enumeración** (siempre 202) + throttle
  por cuenta; el token de reset y los OTP se guardan **solo como hash**. Todo cambio de
  contraseña avisa al dueño por email (`notify_password_changed`). No copiar estos correos a admins.
- **Tests + rate-limit**: el limiter usa storage en memoria que persiste entre tests; hay una
  fixture autouse en `conftest` que lo resetea. Endpoints sensibles de auth usan
  `settings.RATE_LIMIT_LOGIN` (no un literal) para que los tests puedan relajarlo.
- **Lazo cerrado de compras**: recibir una orden (`/compras/ordenes/{id}/recibir`) suma stock de
  consumibles y/o da de alta activos enlazándolos a la orden (alimenta garantías↔proveedor),
  todo en una transacción; solo `BORRADOR` es recibible.
- **Adjuntos XOR**: `INV_ADJUNTO` pertenece a un activo **o** a una orden (CHECK XOR). Bytes en
  volumen local `adjuntos_data:/app/uploads` (dueño `appuser`); para multi-réplica migrar a S3/MinIO.
- **Capas en módulos nuevos**: consumibles/adjuntos/compras/twofactor siguen
  `endpoint→service→repository→DB`; repos solo `flush()`, services commitean. Decrementos de
  stock con UPDATE condicional atómico (espejo de los cupos de licencia). `nullslast()` evitado
  (incompatible con SQLite) — ordenar en Python.

### 16.4 Continuaciones a considerar
**Operativas (antes de producción real):**
1. Configurar `SMTP_PASSWORD` (App Password Gmail) — emails ya disparan, solo falta credencial.
2. Rotar `POSTGRES_PASSWORD`/`REDIS_PASSWORD`/admin según `SECURITY.md` y mover secretos a un gestor.
3. `BACKUP_AGE_RECIPIENT` para cifrar backups; probar deploy con `DOMAIN` real + Let's Encrypt.
4. Subir el logo corporativo real en `SYS_Logo_URL` (hoy placeholder de dummyimage).

**Mejoras de producto / deuda (nice-to-have) — estado a 2026-06-03:**
- **Probar Email-OTP/correos con MailHog** (ofrecido, NO hecho): levantar mailhog +
  `SMTP_HOST=mailhog` para ver Email-OTP de 2FA, reset y avisos en `localhost:8025`.
- **Dashboard**: el usuario optó por NO integrar KPIs de bajo-stock/garantías al dashboard en
  esta ronda (hoy visibles en sus páginas). Pendiente si se quiere proactividad en la home.
- **Recepción de activos**: hoy se crea 1 activo por línea; alta masiva por cantidad N (varios
  seriales por línea) queda como mejora.
- **`garantia_por_vencer`**: conectar `POST /compras/garantias/notificar` a una rutina/cron para
  que sea 100% automático (hoy es a demanda con botón "Notificar a admins").
- **Seed demo** para consumibles/adjuntos/compras (hoy arrancan vacíos; funcional así).
- **Cascada #6 completa**: tipar los modelos existentes en Catálogos → Modelos.
- Tests frontend (Vitest) y E2E (Playwright) — cobertura **sigue en 0**.
- Hash-chain / export a SIEM-WORM para el audit log (hoy append-only a nivel BD).
- Retención/purga del audit log (≥90 días) con rol privilegiado que deshabilite el trigger.
- Adjuntos a S3/MinIO si se quiere multi-réplica (hoy volumen local por nodo).

**Seguridad ya cubierta esta sesión (no re-hacer):** reset por email (token hash, un solo uso,
anti-enum, throttle), aviso de cambio de contraseña, garantía de último super admin, 2FA
TOTP+Email-OTP+recovery (obligatorio admins). Próximos candidatos: forzar cambio de clave en
primer login, "mis sesiones activas" en la UI, WebAuthn/passkeys.

**Cómo validar rápido que todo sigue sano:**
- `cd backend/inventarioTI-backend && pytest` → **136 verdes** (~70s).
- Smoke: login `sa`/`JMpEAgfwlPWLixpmzkSvCrFgA0c`, `https://localhost` HTTP 200,
  `/health/full` interno db+redis ok. OpenAPI: ~202 operaciones.
- Tras tocar modelos: recordar crear la migración encadenada desde `b6c7d8e9f0a1` (la cabeza).

---

## 17. Roles desde el frontend + 3 módulos nuevos (2026-06-03)

Tests: **94 → 113 verdes**. Migraciones nuevas (encadenadas, cabeza actual
**`e3f4a5b6c7d8`**): `2025-12-18_consumibles`, `2025-12-19_adjuntos`,
`2025-12-20_compras`. Todo validado end-to-end contra el stack real
(RBAC con CONSULTA bloqueado en escrituras, robustez 404/422, **0 errores 5xx**).

### 17.1 Definición de roles desde el frontend + bitácora antes→después
Los 4 roles siguen siendo fijos (`SUPER_ADMIN/ADMIN_TI/TECNICO/CONSULTA`); se
mejoró la **asignación** y su trazabilidad:
- **`UserDialog.tsx`**: el desplegable de rol calcula sus opciones según
  `currentUser.role`. Un `ADMIN_TI` solo ve `TECNICO/CONSULTA`; los roles admin
  aparecen únicamente si el editor es `SUPER_ADMIN` (espejo de la regla backend
  `ONLY_SUPER_ADMIN_CAN_GRANT_ADMIN_ROLES`). Ya no se ofrecen opciones que siempre fallan.
- **`services/organization.py::update_usuario`**: el snapshot de auditoría graba
  un bloque `diff` con `{antes, despues}` para `USU_Rol`/`USU_Estado` que cambian,
  más `target_username`. Antes solo se veía el valor nuevo.
- **`AuditPage.tsx`**: el panel de snapshot renderiza el `diff` como chips
  `anterior → nuevo`. Filtros ampliados con las nuevas acciones/entidades.
- Test: `test_role_change_is_audited_with_before_after_diff`.

### 17.2 Consumibles (inventario por cantidad) — prefijo `/consumibles`
Para material no serializado (tóner, cables, periféricos a granel), complementa
los activos por serie.
- Tablas `INV_CONSUMIBLE` (stock actual/mínimo, unidad, categoría) +
  `INV_MOVIMIENTO_CONSUMIBLE` (ENTRADA/SALIDA/AJUSTE con stock resultante).
- **Decremento de stock atómico condicional** (`decrementar_stock`: UPDATE con
  `WHERE stock >= cantidad`) — mismo patrón que los cupos de licencia, sin race,
  nunca negativo. SALIDA sin stock → 409 `INSUFFICIENT_STOCK`.
- Flag calculado `bajo_stock` (`stock <= mínimo`, mínimo>0) + filtro `?bajo_stock=true`.
- Auditoría `STOCK_IN`/`STOCK_OUT`. Borrado bloqueado si hay movimientos (409).
- RBAC: lecturas auth-any; alta/edición/borrado ADMIN; entrada/salida OPERATIVO.
- UI: `features/consumables/` (página + diálogos de alta y de entrada/salida),
  chip ámbar de bajo stock, menú **Consumibles** (grupo Operación).

### 17.3 Adjuntos por activo — prefijo `/adjuntos`
Archivos por activo (factura, foto, acta firmada escaneada).
- Tabla `INV_ADJUNTO` (solo metadatos); los bytes viven en disco en un
  **volumen local** (`adjuntos_data:/app/uploads`). Config en `core/config.py`:
  `UPLOAD_DIR`, `MAX_UPLOAD_SIZE_MB=10`, `ALLOWED_UPLOAD_EXTENSIONS`.
- `services/attachments.py`: valida extensión (lista blanca) y tamaño ANTES de
  escribir; nombre en disco por **uuid** (inmune a path traversal/colisión);
  si falla el commit borra el archivo; descarga vía `FileResponse`.
- **Dockerfile** crea `/app/uploads` con dueño `appuser` → el volumen nombrado
  hereda esa propiedad en su 1ª init (uid 1001 escribe; validado en vivo).
- RBAC: subir OPERATIVO, borrar ADMIN, listar/descargar auth-any. Auditado.
- UI: pestaña **Adjuntos** en el detalle del activo (`AttachmentsSection.tsx`).

### 17.4 Compras, proveedores y garantías — prefijo `/compras`
- Tablas `INV_PROVEEDOR`, `INV_ORDEN_COMPRA`, `INV_ORDEN_COMPRA_LINEA`. Total
  calculado de las líneas; estados `BORRADOR → RECIBIDA | CANCELADA`.
- **Diseño no invasivo**: la línea de orden enlaza opcionalmente a un activo
  (`ACT_Activo`) o consumible. Así la **garantía de un activo deriva su proveedor**
  por LEFT JOIN, **sin modificar `INV_ACTIVO`**.
- `GET /compras/garantias?dias=90&solo_alertas=` clasifica
  `vigente/por_vencer/vencida/sin_garantia` con días restantes (ordena alertas primero).
- RBAC: lecturas auth-any; escrituras ADMIN. Borrar proveedor con órdenes → 409.
- UI: `features/procurement/` — Proveedores (CRUD), Órdenes (líneas dinámicas +
  total en vivo + cambio de estado), Garantías (chips por estado + filtros).
  Nuevo grupo de menú **Compras** en el sidebar.

### 17.5 Convenciones que se respetaron (igual que el resto del sistema)
- Capas `endpoint → service → repository → DB`; repos solo `flush()`, services
  commitean. `internal_error()` mapea `IntegrityError` → 409.
- Migraciones encadenadas desde la cabeza previa (`b0c1d2e3f4a5`); las tablas se
  crean solas en tests (SQLite `create_all`) porque los modelos se importan vía
  la cadena de routers. `nullslast()` evitado (incompatible con SQLite).
- Auditoría en cada mutación con `usuario_id` + IP. Prefijo por columna
  (`CON_`, `MOC_`, `ADJ_`, `PRV_`, `OCO_`, `OCL_`).

### 17.7 Profesionalización: lazo cerrado y automatización
Segunda ronda que convierte los módulos de "captura de datos" en herramientas que
automatizan. Tests: **113 → 120**. Migración `2025-12-21_adjunto_orden` (`f4a5b6c7d8e9`).

- **Recepción de orden (lazo cerrado)** — `POST /compras/ordenes/{id}/recibir`:
  al recibir, las líneas marcadas **suman stock de consumibles** (entrada auditada)
  y/o **dan de alta activos** (alta + código por secuencia + enlace de la línea al
  activo → alimenta garantías↔proveedor). Todo en una transacción. Solo `BORRADOR`
  es recibible (409 `ORDER_NOT_RECEIVABLE`). UI: `ReceiveOrderDialog` (asistente por
  línea: ignorar / reabastecer consumible / crear activo).
- **Alertas por email** (post-commit fire-and-forget, reusan el pipeline SMTP):
  `stock_bajo` se dispara cuando una SALIDA **cruza** el mínimo (no spamea);
  `garantia_por_vencer` es un digest a admins vía `POST /compras/garantias/notificar`
  (a demanda o por cron). Plantillas nuevas en `core/email.py`.
- **Factura/documentos en la orden**: `INV_ADJUNTO` ahora pertenece a un activo **o**
  a una orden (XOR a nivel BD). Endpoints `/adjuntos/ordenes/{id}`. UI: sección de
  adjuntos dentro del detalle de la orden.
- **Vistas de detalle e historial**: `OrderDetailDialog` (cabecera + líneas + factura
  + recibir/cancelar) abriendo al clic en la fila; `ConsumableHistoryDialog` (kardex
  de entradas/salidas con stock resultante).
- **Destinatario en salida de consumible**: el `StockDialog` permite indicar a qué
  persona se entregó (el modelo ya lo soportaba).
- **Export CSV** (BOM UTF-8, anti-inyección) de consumibles, proveedores y órdenes
  (`/export/{consumibles,proveedores,ordenes}.csv`) — paridad con el resto del sistema.

### 17.9 Recuperación de cuenta y garantía de super admin
Migración `2025-12-22_password_reset` (`a5b6c7d8e9f0`). Tests: **120 → 126**.

- **Restablecimiento de contraseña por email** (flujo "olvidé mi clave"):
  - `POST /login/password-reset/request {identifier}` (username o correo): **anti-enumeración**
    (responde siempre 202 igual), rate-limited. Si la cuenta existe/activa/con correo,
    genera un token aleatorio (`secrets.token_urlsafe(32)`) y lo envía **SOLO al correo
    corporativo** del usuario (cc_admins=False) — esa es la validación de que la
    solicitud corresponde al dueño del correo.
  - `POST /login/password-reset/confirm {token, new_password}`: valida token (un solo
    uso, no expirado, expiry `PASSWORD_RESET_EXPIRE_MINUTES=30`), aplica política,
    fija la clave, marca el token usado y **revoca todos los tokens** del usuario.
  - Tabla `SYS_PASSWORD_RESET` guarda **solo el hash SHA-256** del token (una fuga de
    BD no expone tokens usables); `secrets`/`hashlib` en `core/security.py`; plantilla
    `password_reset` en `core/email.py`; purga de expirados en `purge_expired_security_records`.
  - Frontend: link "¿Olvidaste tu contraseña?" en `LoginPage` → `ForgotPasswordDialog`;
    ruta pública `/reset-password?token=...` → `ResetPasswordPage`.
- **Garantía "nunca sin super admin"** (validada en vivo): la protección ya existía en
  ambas rutas — `update_usuario` (degradar/desactivar) y `offboarding_persona`
  (`CANNOT_OFFBOARD_LAST_SUPER_ADMIN`) — pero estaba **eludida** porque la BD demo tenía
  un `puppet_consulta` con rol SUPER_ADMIN (resto de la demo de escalada). Se limpió
  (auditado, vía API): `sa` reactivado, `puppet_consulta`→CONSULTA+inactivo,
  `puppet_admin`/`testuser_*` desactivados. Con `sa` como único super admin activo,
  `DELETE`/degradar `sa` → **400 CANNOT_DISABLE_LAST_SUPER_ADMIN**. Test de regresión
  `test_no_se_puede_desactivar_el_ultimo_super_admin`.
- **Aviso de seguridad al usuario** (plantilla `password_changed`, helper
  `notify_password_changed`): cuando una contraseña cambia se avisa **solo al dueño**
  de la cuenta (cc_admins=False) con método (autoservicio / restablecimiento /
  cambio por administrador), fecha e IP, y un "¿no fuiste tú?". Cableado en
  `/me/password`, `/login/password-reset/confirm` y `update_usuario` (admin).
- **Throttle por cuenta de los reset** (`PASSWORD_RESET_REQUEST_COOLDOWN_MINUTES=2`):
  además del rate-limit por IP, no se emite otro correo si ya se solicitó uno en la
  ventana — frena el bombardeo de emails a una víctima desde IPs rotativas. Respuesta
  202 genérica igualmente (anti-enumeración). Tests con la ventana activada por monkeypatch.
- **Nota operativa**: los emails de reset/aviso usan el mismo pipeline SMTP; sin
  `SMTP_HOST` configurado se loguean pero no se entregan (igual que el resto).
- Fix de tests: fixture autouse en conftest resetea el rate-limiter en memoria entre
  tests (evita 429 por acumulación de llamadas a endpoints con límite literal).

### 17.10 2FA / MFA (TOTP + Email-OTP)
Migración `2025-12-23_two_factor` (`b6c7d8e9f0a1`). Tests: **130 → 136**.
Dependencias nuevas: `pyotp`, `qrcode`.

- **Dos métodos** por usuario: **TOTP** (app autenticadora, RFC 6238) y **Email-OTP**
  (código de 6 dígitos por correo en cada login). Más **códigos de recuperación**
  (un solo uso) por si se pierde el 2º factor.
- **Login en dos pasos**: si el usuario tiene 2FA, `/login/access-token` con
  contraseña correcta NO entrega tokens; devuelve `{requires_2fa, method,
  challenge_token}` (JWT efímero tipo "2fa"). `POST /login/2fa/verify {challenge,
  code}` valida el TOTP/OTP o un código de recuperación y recién ahí entrega los
  tokens. Rate-limited + auditado (LOGIN_FAILED reason bad_2fa_code).
- **Enrolamiento** (`/me/2fa/*`, JWT requerido): `totp/setup` (secreto + QR PNG en
  data-URI) → `totp/activate {code}`; `email/setup` (envía OTP) → `email/activate
  {code}`; `disable {password}`; `recovery-codes/regenerate`. El secreto TOTP se
  guarda **cifrado (Fernet)**; OTP de email y recovery solo como hash SHA-256.
- **Obligatorio para roles admin** (`TWO_FACTOR_REQUIRED_ROLES=SUPER_ADMIN,ADMIN_TI`):
  esos roles no pueden desactivar su 2FA (403 `2FA_REQUIRED_FOR_THIS_ROLE`). Tope de
  intentos por OTP de email (`TWO_FACTOR_MAX_ATTEMPTS`), expiraciones configurables,
  y purga de OTP en `purge_expired_security_records`.
- Modelo: columnas `USU_2FA_Habilitado/Metodo/Secret` en INV_USUARIO + tablas
  `SYS_2FA_CODE` (OTP email) y `SYS_2FA_RECOVERY`. `UsuarioResponse` expone el estado
  (badge "2FA" en la lista de usuarios).
- Frontend: paso de código en `LoginPage`; `TwoFactorDialog` (enrolar con QR/email,
  ver códigos de recuperación una vez, desactivar/regenerar) abierto desde el sidebar.
- **Nota**: el Email-OTP usa el mismo SMTP; sin `SMTP_HOST` el código se loguea pero
  no se entrega. TOTP funciona sin SMTP (offline). Validado en vivo end-to-end (TOTP).

### 17.8 Pendientes / nice-to-have de estos módulos
- Seed demo para los 3 módulos (hoy arrancan vacíos; el sistema es funcional así).
- Adjuntos: migrar storage a S3/MinIO si se quiere multi-réplica (hoy volumen local
  por nodo) — reemplazar la capa de storage en `services/attachments.py`.
- KPI de bajo-stock/garantías en el **Dashboard** (hoy en sus páginas; el usuario
  optó por no integrarlo al dashboard en esta ronda).
- Recepción de activos: hoy se crea 1 activo por línea; un alta masiva por cantidad
  N (varios seriales por línea) quedaría como mejora.
- `garantia_por_vencer`: conectar `POST /compras/garantias/notificar` a una rutina
  programada (cron/routine) para que sea 100% automático.
- Tests frontend (Vitest) y E2E (Playwright) siguen en 0.

> **Higiene de usuarios (detectado 2026-06-03):** la BD demo acumuló cruft de
> sesiones previas: `sa` había quedado **inactivo** (reactivado), y existen
> `puppet_consulta` (rol SUPER_ADMIN — resto de la demo de escalada), `puppet_admin`
> y `testuser_*`. Conviene desactivar/eliminar esos usuarios de prueba antes de
> producción (el `puppet_consulta` SUPER_ADMIN es un riesgo a cerrar).

---

## 18. Endpoints, RBAC e integridad de datos (2026-06-05)

Ronda de **estructura/validación de endpoints, seguridad por rol e integridad
del flujo de datos**. Base de partida: 136 tests verdes. Resultado: **136 tests
verdes** (sin regresiones) + guard RBAC automatizado.

### 18.1 Integridad transaccional — manejo de `IntegrityError` unificado
Migrados los `db.commit()` "desnudos" al helper `commit_or_409` (un único punto
que traduce `IntegrityError -> 409`, antes podían escapar como 500):

- **`services/software.py`**: todo el CRUD de tipos-licencia/software/licencias +
  `registrar_instalacion`/`desinstalar`. Se respetó el `except` específico de
  `delete_licencia` (mensaje de dominio `CANNOT_DELETE_LICENSE_IN_USE`).
- **`services/traceability.py`**: CRUD de tipos + `offboarding_persona` y
  `registrar_devolucion`. **No** se tocó el `commit` de `registrar_movimiento`
  ni `registrar_transferencia`: ya tienen `except IntegrityError` con mensaje de
  dominio (`ASSET_ALREADY_HAS_OPEN_MOVEMENT`) que `commit_or_409` degradaría.
- **`services/twofactor.py`**: `totp_setup`, `disable`, `_new_recovery_codes`,
  `_issue_email_otp` (commits antes sin protección → cierre de carrera por OTP
  concurrente daba 500).

> Decisión clave: se usó `commit_or_409` en vez de `@transactional` porque varios
> métodos envían **email post-commit**; `@transactional` movería el commit al
> final y reordenaría/duplicaría el correo. `commit_or_409` conserva el punto de
> commit exacto. (Nota: `core.py`/`consumable.py`/`procurement.py` ya eran
> 409-safe vía `internal_error`, que también traduce `IntegrityError -> 409`.)

### 18.2 Validación de entrada (Pydantic) — cotas alineadas a la BD
Se añadieron `max_length`/rangos en schemas de escritura para que un dato fuera
de rango devuelva **422 limpio** en vez de un `DataError`/500:

- Cotas `String(n)` alineadas al tamaño de columna (seguro también para los
  `Response`, porque la BD ya garantiza `<= n`): `location` (dirección, alias,
  área), `catalogs` (TCN/EOP descripción), `software` (TLI descripción),
  `organization` (CAR descripción).
- Campos `Text` (sin límite en BD → vector de abuso): cota **solo en la entrada**
  (override en el schema `Create`, base laxa para no romper la serialización de
  datos legados largos): `MOV_Observacion` (1000), `MAN_Descripcion_Falla` (2000).
- Igual criterio "solo-entrada" para `LIC_Clave_Activacion` (se cifra antes de
  guardar; el `Response` devuelve el texto descifrado) y `MOD_Anio_Lanzamiento`
  (rango 1970–2100, sin restringir respuestas de modelos legados).
- **`USU_Password`**: `max_length=128` (acota el coste de hashing bcrypt → evita
  DoS por password gigante).

> Se evitó tocar el `code` de 2FA: el mismo campo recibe **códigos de
> recuperación** (más largos, con guiones) en `verify_login`; acotarlo a 6–8
> habría roto ese login.

### 18.3 RBAC — matriz documentada + guard automatizado
- **Invariante verificado**: **0 endpoints mutadores sin guard de rol** (fuera del
  autoservicio `login`/`2fa`). `POST /core/activos/search` usa POST por el cuerpo
  de filtros pero es de lectura.
- **`docs/RBAC_MATRIX.md`**: matriz rol↔módulo (incluye el 4º rol `CONSULTA`,
  solo lectura) y las lecturas accesibles a `CONSULTA`.
- **`scripts/check_rbac.py`**: guard que falla si un mutador carece de `require_*`
  (apto para CI). Verde en la imagen reconstruida.
- **Decisión de negocio**: `CONSULTA` mantiene **visibilidad completa de lectura**
  (PII, comercial, adjuntos) — rol de auditoría/gerencia. Documentado, sin cambio
  de código.

### 18.4 Validación
Imagen `backend` reconstruida (`docker compose up -d --build backend`), sana.
`scripts/check_rbac.py` OK + **136 tests verdes** contra la imagen horneada.

---

## 19. Configuración, color de fondo y traducciones completas (2026-06-05)

### 19.1 Limpieza de usuario
`puppet_consulta` ya estaba **inactivo** y con rol `CONSULTA` (la nota previa de
"SUPER_ADMIN" estaba desactualizada). Único super admin activo: `sa`. Sin acción
destructiva necesaria.

### 19.2 Color de fondo configurable (end-to-end)
Antes el fondo era fijo `#0f172a` y el "Color Primario" solo teñía el brillo del
gradiente (etiqueta engañosa). Ahora:
- **Backend**: nueva columna `SYS_Color_Fondo` en `SYS_CONFIGURACION` + campo en
  `ConfigUpdate/Response` (patrón hex validado). Migración `c7d8e9f0a1b2`
  (`2026-06-05_config_color_fondo`), aplicada. Repo de config ya era genérico.
- **Frontend**: `theme.ts` recibe `backgroundColor` y deriva **modo
  claro/oscuro, texto, paper y bordes por luminancia** (legible con cualquier
  color). `ConfigContext`/`configService`/`App.tsx` propagan el campo.

### 19.3 Página de Configuración rediseñada
`ConfigPage.tsx` reescrita: tarjetas de sección uniformes (Identidad / Apariencia
/ Actas), selector de color con hex editable + swatch, **presets de fondo
oscuros**, **vista previa en vivo** del tema, y etiquetas corregidas
("Primario = brillo de marca", "Secundario = botones"). Logo con preview integrado.

### 19.4 Traducciones completas y coherentes
Auditoría i18n: **255 claves se usaban solo por texto *fallback* en español** (es
decir, módulos enteros —auth, 2FA, consumibles, mantenimiento, compras,
operaciones, adjuntos, etc.— no estaban traducidos para EN/IT). Se extrajo el
español fuente, se tradujo a EN e IT y se fusionó en las locales anidadas.
Resultado: **es/en/it con 517 claves cada uno (paridad perfecta)** y **0 claves
usadas en el código sin definir**.

### 19.5 Validación
- `alembic head = c7d8e9f0a1b2`; `GET /gov/config` devuelve `SYS_Color_Fondo`.
- `scripts/check_rbac.py` OK + **136 tests backend verdes** (imagen reconstruida).
- Frontend `tsc -b && vite build` sin errores; imagen reconstruida.
- End-to-end vía Caddy: app `HTTP 200`, API de config OK. Contenedores sanos.

---

## 20. Contraste WCAG, reset MFA, bug de subida y coherencia (2026-06-05)

### 20.1 Bug de subida de facturas/actas (422) — RESUELTO
`POST /adjuntos/ordenes/{id}` devolvía **422** (confirmado en logs). Causa: el
cliente axios fijaba `Content-Type: application/json` como default de instancia,
que **no se reemplaza** para `FormData` → el multipart viajaba sin boundary y
FastAPI no parseaba `file`. Fix: quitar el default global en `src/api/axios.ts`
(axios pone JSON para objetos y multipart para FormData). El almacenamiento
(volumen `adjuntos_data`) y la whitelist ya eran correctos.

### 20.2 Reset de MFA por Super Admin — NUEVO
Antes todo el 2FA era autoservicio (`/me/2fa/*`). Ahora:
- `POST /org/usuarios/{id}/2fa/reset` (`require_super_admin`), servicio
  `OrganizationService.reset_2fa` que limpia `USU_2FA_*` + recovery codes +
  email OTPs (reutiliza `gov_repo.delete_recovery_codes/invalidate_email_otps`),
  audita `2FA_RESET_BY_ADMIN`. No pide la contraseña del objetivo.
- UI: acción "Resetear MFA" en `UsersPage` (visible a SUPER_ADMIN cuando el
  usuario tiene 2FA), con confirmación. Tests: +2 (reset OK 200, no-SA 403).

### 20.3 Contraste WCAG calculado — NUEVO motor + barrido completo
- `src/theme/contrast.ts`: luminancia relativa WCAG + ratio de contraste +
  `pickText`/`muteText`/`ensureReadable`/`mix` (cálculo matemático puro).
- `theme.ts` deriva del fondo: `text.primary` (mayor contraste, ~AAA),
  `text.secondary` (≥4.5 atenuado), `divider`, `background.paper`, acento
  primario legible y **paleta de estado** (success/warning/error/info) ajustada.
- Barrido: ~250 colores hardcodeados (`white`, `rgba(30,41,59)`, `#38bdf8`,
  `#94a3b8`, estados) → tokens del tema en ~25 pantallas/componentes. KPIs del
  dashboard pasan por `ensureReadable` contra el fondo.
- Verificado: el texto elegido cumple **≥4.5:1** en todos los presets, en blanco
  y en colores medios.

### 20.4 Cascada de catálogos (no abrumar)
`GET /cat/modelos` acepta `tipo_id`; `AssetDialog` carga modelos filtrados por
**Marca + Tipo** desde el backend (antes traía todos y filtraba en cliente).

### 20.5 Análisis del flujo de negocio (verificado)
- **Consumibles**: alta (nombre único) → entrada/salida atómica con snapshot de
  stock y alerta de bajo stock (email best-effort). `SALIDA` falla si stock
  insuficiente. CHECK `stock >= 0`.
- **Proveedores**: CRUD; no se pueden borrar si tienen órdenes (FK RESTRICT).
- **Órdenes**: estados `BORRADOR → RECIBIDA | CANCELADA` (sin transiciones desde
  estados finales). Creación con líneas descriptivas (sin enlace aún).
- **Recepción (lazo cerrado)** `recibir_orden`: en UNA transacción suma stock de
  consumibles, da de alta activos (estado "Disponible", código por prefijo) y
  enlaza cada línea; marca la orden RECIBIDA. Atómico (todo o nada).
- **Garantías**: derivadas de `ACT_Fecha_Compra`/`ACT_Fin_Garantia`
  (vigente/por_vencer/vencida/sin_garantia), ventana configurable, notificación
  on-demand a admins.

Diferidos (requieren migración, fuera de alcance esta ronda): CHECK
`ACT_Activo XOR CON_Consumible` por línea, estado "Disponible" canónico en
config, `TAC_Prefijo` requerido, "sin_garantía" como alerta.

### 20.6 Validación
`pytest tests/` = **138 verdes** (136 + 2 de reset MFA). `npm run build`
(tsc + vite) sin errores. `scripts/check_rbac.py` OK. Imágenes reconstruidas.
