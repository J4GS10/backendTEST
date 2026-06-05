# Guía de despliegue — Sistema de Inventario TI

Cómo levantar **todo el stack en limpio** (Postgres + Redis + Backend + Frontend +
Caddy/TLS), configurado correctamente y **sin datos de prueba**: solo los *seeds*
canónicos que el sistema necesita para funcionar.

- Backend (este repo): `inventario-ti-backend`
- Frontend (repo hermano): `inventario-ti-frontend`
- Kit de despliegue: carpeta [`deploy/`](deploy) (compose + Caddyfile + `.env.example`)

---

## 1. Qué se levanta

| Servicio | Imagen / build | Expuesto | Rol |
|---|---|---|---|
| `caddy` | caddy:2-alpine | **80/443** (único público) | TLS automático + reverse proxy |
| `frontend` | build (Nginx) | interno | SPA React + proxy `/api` → backend |
| `backend` | build (Gunicorn) | interno | API FastAPI |
| `db` | postgres:16-alpine | interno | Base de datos |
| `redis` | redis:7-alpine | interno | Caché de auth + rate-limit |

Solo Caddy publica puertos; DB, Redis y backend viven en la red interna de Docker.

---

## 2. Requisitos

- **Docker** + **Docker Compose v2** (`docker compose version`).
- Para TLS real: un **dominio** apuntando (DNS A/AAAA) al servidor y los puertos
  **80 y 443** abiertos. Para pruebas locales basta `DOMAIN=localhost` (cert autofirmado).
- ~2 GB de RAM libres (límites por contenedor ya configurados).

---

## 3. Clonar los dos repos (como hermanos)

El compose espera los dos repositorios **en el mismo directorio padre**:

```bash
mkdir inventario-ti && cd inventario-ti
git clone https://github.com/J4GS10/inventario-ti-backend.git
git clone https://github.com/J4GS10/inventario-ti-frontend.git
```

Resultado:

```
inventario-ti/
├── inventario-ti-backend/      ← este repo (compose en deploy/)
└── inventario-ti-frontend/     ← repo hermano (build context del frontend)
```

---

## 4. Configurar (.env con secretos)

```bash
cd inventario-ti-backend/deploy
cp .env.example .env
```

Genera y pega secretos **fuertes y únicos** (no reutilices los de ejemplo):

```bash
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
python -c "from cryptography.fernet import Fernet; print('FIELD_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
python -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))"
python -c "import secrets; print('REDIS_PASSWORD=' + secrets.token_urlsafe(24))"
python -c "import secrets; print('SUPER_ADMIN_PASSWORD=' + secrets.token_urlsafe(16))"
```

Edita en `.env` como mínimo:

| Variable | Qué poner |
|---|---|
| `POSTGRES_PASSWORD` | contraseña generada |
| `SECRET_KEY` | generada (firma JWT) |
| `FIELD_ENCRYPTION_KEY` | clave Fernet generada (cifra claves de licencia) |
| `REDIS_PASSWORD` | generada — **debe coincidir** con la de `REDIS_URL` |
| `REDIS_URL` | `redis://:<REDIS_PASSWORD>@redis:6379/0` |
| `SUPER_ADMIN_PASSWORD` | contraseña del primer admin `sa` |
| `SUPER_ADMIN_EMAIL` | correo real del admin |
| `DOMAIN` | `localhost` o tu dominio real |
| `ACME_EMAIL` | tu correo (avisos de Let's Encrypt) |
| `SEED_DEMO` | **`false`** (no cargar data de prueba) |

> SMTP es opcional: si dejas `SMTP_HOST` vacío, los correos solo se loguean (el sistema
> funciona igual). Para activarlos, configura un proveedor (Brevo/SendGrid/Gmail…).

---

## 5. Levantar el stack

```bash
# desde inventario-ti-backend/deploy
docker compose up -d --build
docker compose ps          # los 5 servicios deben quedar "healthy"
```

En el primer arranque el backend ejecuta automáticamente (ver `entrypoint.sh`):

1. `alembic upgrade head` — crea/actualiza el esquema.
2. `init_prod` — crea la **configuración** y el usuario **`sa`** (SUPER_ADMIN) con
   `SUPER_ADMIN_PASSWORD`. Idempotente.
3. `seed_min` — **seed mínimo canónico** (ver §6). Idempotente, seguro en producción.
4. *(NO se cargan datos demo: `SEED_DEMO=false` + `ENVIRONMENT=production`.)*

Accede:
- `DOMAIN=localhost` → `https://localhost` (acepta el aviso del cert autofirmado).
- Dominio real → `https://tu-dominio.com` (Caddy emite el certificado solo).

---

## 6. Datos de arranque: solo lo necesario (sin basura)

Un despliegue limpio queda con **únicamente** lo que el sistema necesita para operar.
`app/seed_min.py` siembra (idempotente, solo si falta):

- **Estados operativos** (REQUERIDOS por la lógica de transición): `Disponible`,
  `Asignado`, `En Reparación`, `Baja`, `En Bodega`. Sin ellos fallan asignar/devolver/
  transferir/recibir-orden/dar-de-baja.
- **Tipos de movimiento** (REQUERIDOS): `Ingreso`, `Asignación`, `Devolución`,
  `Préstamo`, `Transferencia`.
- **Tipos de mantenimiento**: `Preventivo`, `Correctivo`, `Predictivo`.
- **Tipos de especificación**: RAM, Almacenamiento, Procesador, etc.
- **Tipos de evidencia**: Fotografía, Acta firmada, Reporte técnico.

**No** crea personas, activos, usuarios, marcas, modelos ni movimientos: todo eso lo
das de alta tú desde la app. Marcas, modelos, tipos de activo, ubicaciones y
departamentos son **datos tuyos** (se crean en los catálogos de la UI).

> Los datos DEMO (usuarios `puppet_*`, personas/activos de ejemplo) viven en
> `app/seed_demo.py` y **están deshabilitados en producción**: el `entrypoint.sh`
> aborta si `SEED_DEMO=true` con `ENVIRONMENT=production`. Así no entra basura por error.

---

## 7. Primer acceso

1. Entra a la URL con usuario **`sa`** y `SUPER_ADMIN_PASSWORD`.
2. Como `sa` es SUPER_ADMIN, el sistema **exige 2FA**: enrola TOTP (app autenticadora)
   o Email-OTP en *Mi cuenta → 2FA*. Guarda los códigos de recuperación.
3. Cambia la contraseña inicial.
4. Crea tus catálogos (marcas, modelos, tipos de activo), ubicaciones, departamentos,
   personas y demás usuarios desde la UI.

---

## 8. Operación

```bash
cd inventario-ti-backend/deploy

docker compose ps                         # estado
docker compose logs -f backend            # logs en vivo
docker compose exec backend alembic current   # revisión de BD

# Re-seed canónico manual (idempotente; normalmente innecesario)
docker compose exec backend python -m app.seed_min

# Backup de la BD
docker compose exec db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup_$(date +%F).sql

# Restore
cat backup_AAAA-MM-DD.sql | docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

### Actualizar a una versión nueva (redeploy)

```bash
cd inventario-ti-backend && git pull
cd ../inventario-ti-frontend && git pull
cd ../inventario-ti-backend/deploy
docker compose up -d --build              # rebuild + migraciones automáticas en el arranque
```

---

## 9. Empezar completamente de cero (borrar TODO)

> ⚠️ Destruye la base de datos y los adjuntos. Úsalo solo si quieres un entorno virgen.

```bash
cd inventario-ti-backend/deploy
docker compose down -v        # -v elimina los volúmenes (postgres_data, adjuntos_data, caddy_*)
docker compose up -d --build  # arranca limpio: esquema + sa + seed mínimo, sin nada más
```

---

## 10. Checklist antes de producción

- [ ] `.env` con **todos** los `CAMBIAR` reemplazados por secretos únicos y fuertes.
- [ ] `SEED_DEMO=false`.
- [ ] `DOMAIN` real + DNS apuntando + puertos 80/443 abiertos (TLS Let's Encrypt).
- [ ] `BACKEND_CORS_ORIGINS` con tu dominio (`["https://tu-dominio.com"]`).
- [ ] `SUPER_ADMIN_PASSWORD` fuerte; cambiar tras el primer login y enrolar 2FA.
- [ ] SMTP configurado si quieres notificaciones por correo.
- [ ] El `.env` **no** se sube a git (ya está en `.gitignore`).
- [ ] Backups programados (`pg_dump`) y probados con un restore.
- [ ] Guardar `SECRET_KEY` y `FIELD_ENCRYPTION_KEY` en un gestor de secretos: si pierdes
      `FIELD_ENCRYPTION_KEY` no podrás descifrar las claves de licencia guardadas.

---

## 11. Problemas comunes

| Síntoma | Causa / solución |
|---|---|
| Backend reinicia / unhealthy | Revisa `docker compose logs backend`. Falta un secreto en `.env` (p.ej. `FIELD_ENCRYPTION_KEY`) o Redis no autentica (revisa que `REDIS_PASSWORD` coincida en `REDIS_URL`). |
| `redis` no arranca | `REDIS_PASSWORD` vacío. Ponle un valor. |
| Frontend no compila | Verifica que `inventario-ti-frontend` esté **clonado como hermano** del backend. |
| Aviso de certificado en el navegador | Normal con `DOMAIN=localhost` (autofirmado). Con dominio real, Caddy emite Let's Encrypt válido. |
| Asignar/recibir orden da error de "estado faltante" | Faltó el seed canónico. Ejecuta `docker compose exec backend python -m app.seed_min`. |
| `entrypoint` aborta por `SEED_DEMO=true` | En producción no se permite data demo. Pon `SEED_DEMO=false`. |

---

### Documentación relacionada
- [`docs/README.md`](docs/README.md) — índice de toda la documentación del proyecto.
- [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) · [`docs/SEGURIDAD.md`](docs/SEGURIDAD.md)
- [`docs/ORACLE_MIGRATION_RUNBOOK.md`](docs/ORACLE_MIGRATION_RUNBOOK.md) — migrar la BD a Oracle.
