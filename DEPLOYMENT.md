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

### 4.1 Correo corporativo y Active Directory (opcional)

**Forma recomendada: desde la interfaz.** En *Administración → Directorio y
notificaciones → Cuenta de servicio y correo*, un SUPER_ADMIN elige el modo:

| Modo | Qué hace |
|---|---|
| Desactivado | No se envían correos (quedan en el log) |
| Solo correo | Una **cuenta genérica dedicada** (p. ej. `inventario@empresa.com` + clave) envía todos los correos |
| Correo + Active Directory | La **misma cuenta** también se usa para conectarse al AD (bind LDAP) y así escalar con personas, jefes y grupos |

Lo que infraestructura debe entregar:

1. **Una cuenta de servicio** en el AD local, con buzón. Si el mismo correo se usa
   para el AD, la cuenta debe existir en el AD *local*: una cuenta que solo vive en la
   nube de M365 no puede conectarse por LDAP. Conviene configurarla con "la contraseña
   nunca expira", sin privilegios, y ponerle un buzón o alias como remitente.
2. **Cómo envía esa cuenta**, según el servidor:
   - **Exchange local:** envío autenticado por `587/STARTTLS` con la cuenta, o un
     conector de *relay* por IP. En el relay la clave puede quedar vacía.
   - **Microsoft 365:** Microsoft retiró (o está retirando) la autenticación básica
     para enviar por SMTP. Usen el proveedor **Microsoft Graph**: un registro de
     aplicación en Entra ID con el permiso de *aplicación* `Mail.Send`, restringido al
     buzón de servicio con una *Application Access Policy*. En la pantalla se cargan el
     tenant, el client ID y el secreto.
   - **Google Workspace:** `smtp.gmail.com:587` con una contraseña de aplicación
     (requiere verificación en 2 pasos).
3. **Para el AD:** LDAPS (`ldaps://dc01.empresa.local`) con el certificado de la CA
   interna (`AD_CA_CERT_FILE`), la OU de empleados y el grupo de admins de TI.

Con **Enviar correo de prueba** y **Probar conexión AD** se validan los valores
*antes* de guardarlos. Las claves se guardan cifradas (`FIELD_ENCRYPTION_KEY`), nunca
se devuelven por la API y no aparecen en la auditoría.

**Protección de la cuenta:** tras un fallo de autenticación, el sistema **pausa 15 min**
los envíos y las consultas al AD. Sin esta pausa, los reintentos de la cola repetirían
la clave incorrecta hasta que la política de bloqueo del AD bloqueara la cuenta, y eso
tumbaría el correo y el AD a la vez. Mientras dura la pausa, los correos esperan en la
cola sin gastar reintentos. Guardar credenciales nuevas, o pulsar *Reanudar ahora*,
levanta la pausa.

**Alternativa: variables de entorno.** Si nunca se guardó nada desde la interfaz, se
usan las variables `SMTP_*` y `AD_*` de abajo. Una vez guardada la configuración en la
interfaz, **esa tiene prioridad**.

**Envío (SMTP).** Con el servidor de correo de la empresa:

| Servidor | Configuración |
|---|---|
| Exchange on-premise | Conector de *relay* anónimo que acepte la IP del servidor del inventario → `SMTP_HOST=exchange.empresa.local`, `SMTP_PORT=25`, `SMTP_USER`/`SMTP_PASSWORD` vacíos |
| Microsoft 365 | `SMTP_HOST=smtp.office365.com`, `SMTP_PORT=587`, cuenta de servicio con *SMTP AUTH* habilitado en el buzón |

`SMTP_FROM_EMAIL` debe ser un buzón/alias existente (p. ej. `inventario@empresa.com`).

**Directorio (LDAP).** Permite sincronizar personas, jefes y departamentos desde AD
y usar grupos de AD como destinatarios. Requiere una cuenta de servicio de **solo
lectura** (usuario de dominio normal, sin privilegios):

```env
AD_ENABLED=true
AD_SERVER=ldaps://dc01.empresa.local          # CSV para varios DC; LDAPS (636) recomendado
AD_START_TLS=false                            # true si se usa ldap:// (389) con StartTLS
AD_CA_CERT_FILE=/app/certs/ca-empresa.pem     # CA interna que firma el certificado del DC
AD_BIND_USER=svc_inventario@empresa.local     # formato UPN
AD_BIND_PASSWORD=********
AD_BASE_DN=OU=Usuarios,DC=empresa,DC=local    # OU con los empleados a sincronizar
AD_ADMIN_GROUP=GG-Inventario-TI               # sus miembros reciben copia de todos los eventos
AD_SYNC_INTERVAL_MINUTES=60                   # 0 = solo sincronización manual
```

En producción se rechaza un bind por LDAP sin cifrar (la contraseña viajaría en claro).
Luego, en **Administración → Directorio y notificaciones**: *Probar conexión* →
*Simular sincronización* (no guarda nada) → *Sincronizar ahora*, y definir las reglas de
destinatarios por gestión (afectado, jefe inmediato, admins, grupos de AD, correos fijos).

Las personas deshabilitadas en AD se desactivan automáticamente **solo si no tienen
activos asignados**; las que tienen activos se listan como pendientes y se notifica a
los admins para que procesen el offboarding.

### 4.3 Identidades, accesos y MFA

**Roles y separación de funciones:**

| Rol | Ámbito |
|---|---|
| `SUPER_ADMIN` | Configuración del sistema y cualquier cuenta |
| `ADMIN_SEGURIDAD` | Identidades y accesos: crear usuarios, asignar roles operativos, restablecer contraseñas y MFA, desbloquear, cerrar sesiones, leer la auditoría. **Sin acceso al inventario** |
| `ADMIN_TI` / `TECNICO` / `CONSULTA` | Operación del inventario. **No administran cuentas** |

- Nadie puede aplicarse acciones administrativas a sí mismo; lo propio se gestiona en *Seguridad de la cuenta*.
- `ADMIN_SEGURIDAD` no puede gestionar ni otorgar `SUPER_ADMIN` ni `ADMIN_SEGURIDAD`. Esos roles solo los asigna un `SUPER_ADMIN`.
- Restablecer una contraseña genera una **temporal**: se muestra una sola vez, obliga a cambiarla en el siguiente inicio de sesión, desbloquea la cuenta y cierra sus sesiones. El administrador nunca conoce la contraseña definitiva.

**MFA obligatorio** (`TWO_FACTOR_REQUIRED_ROLES`, por defecto `SUPER_ADMIN,ADMIN_SEGURIDAD,ADMIN_TI`). Una cuenta con uno de esos roles que no tenga MFA entra en una sesión restringida y **debe enrolar un segundo factor** antes de usar el sistema. Las cuentas SSO delegan la contraseña y el MFA en el proveedor de identidad.

> **Al desplegar esta versión:**
> 1. `sa` y los `ADMIN_TI` sin MFA deberán configurar una app autenticadora (Microsoft Authenticator, Google Authenticator…) en su próximo inicio de sesión. Tengan un teléfono a mano.
> 2. Los `ADMIN_TI` dejan de administrar usuarios. Un `SUPER_ADMIN` debe asignar el rol `ADMIN_SEGURIDAD` a quien gestionará las cuentas.
> 3. Guarden los códigos de recuperación en un lugar seguro. Si alguien pierde el teléfono, un administrador puede *Restablecer MFA* desde *Usuarios y accesos*.

**Controles adicionales:** los códigos TOTP no se pueden reutilizar (anti-replay). Los códigos del segundo factor fallidos cuentan para el bloqueo de la cuenta igual que las contraseñas. Todas las acciones administrativas quedan en la auditoría, sin secretos.

**Rol `AUDITOR`:** solo lectura del inventario de su alcance, más la bitácora de auditoría (filtrada por sus sedes) y su exportación. No tiene ninguna operación de escritura.

### 4.4 Alcance de datos por sede (RLS)

Cada cuenta de inventario (`ADMIN_TI`, `TECNICO`, `AUDITOR`, `CONSULTA`) ve y modifica
solo la información de sus **sedes**, o de todas si tiene **alcance global**.
`SUPER_ADMIN` y `ADMIN_SEGURIDAD` son siempre globales. Se asigna en *Usuarios y
accesos*: `ADMIN_SEGURIDAD` asigna sedes; solo un `SUPER_ADMIN` otorga el alcance
global. Una cuenta sin sedes no ve datos.

- Activos, personas, órdenes de compra y consumibles tienen sede propia.
  Movimientos, mantenimientos, especificaciones, instalaciones, adjuntos y
  evidencias heredan la de su activo u orden.
- La sede de un activo **sigue al área** de su último movimiento: asignarlo o
  transferirlo a un área de otra sede lo mueve de sede (el área de destino debe
  estar en el alcance de quien opera).
- País, estado, municipio y sede solo los modifica alguien con alcance global;
  edificios, niveles y áreas, quien tenga la sede.

**Dos capas independientes:**

1. **Aplicación** (todos los motores): filtro automático de SQLAlchemy en cada
   consulta, incluidas las relaciones.
2. **PostgreSQL**: políticas RLS reales. Las consultas de usuarios se ejecutan con
   el rol sin privilegios `DB_RLS_ROLE` (por defecto `inventario_rls`) mediante
   `SET LOCAL ROLE`, así que la base filtra **aunque el backend se conecte como
   superusuario**. La bitácora es de solo inserción para ese rol.

La migración crea el rol, los permisos, las funciones y las políticas. Si el usuario
de la migración **no puede crear roles** (bases gestionadas), un administrador de la
base debe crear el rol y concederlo, y después reinstalar las políticas:

```sql
CREATE ROLE inventario_rls NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT;
GRANT inventario_rls TO <usuario_de_la_app>;
```
```bash
docker compose exec backend python -m app.db.install_rls
```

Al arrancar, el backend verifica la capa RLS: si falta, lo registra como error
(`rls.db_layer_unavailable`) y el panel *Usuarios y accesos* lo muestra. El
alcance sigue aplicándose en la aplicación.

> **Al desplegar esta versión** no se corta ningún acceso: las cuentas de inventario
> existentes quedan con **alcance global** (como hasta ahora) y la sede de cada
> activo y persona se deduce de su última asignación (con una sola sede, todo queda
> en ella). Después, restrinja cada cuenta a sus sedes en *Usuarios y accesos*.

### 4.5 Sesiones, contraseñas y cuentas

| Variable | Default | Efecto |
|---|---|---|
| `PASSWORD_HISTORY_COUNT` | 5 | No se puede reutilizar ninguna de las últimas N contraseñas |
| `PASSWORD_BLOCKED_WORDS` | `lombardi,inventario,…` | Palabras prohibidas (además de la lista de contraseñas comunes, el usuario y el nombre/correo del titular) |
| `NEW_DEVICE_ALERT_ENABLED` | true | Aviso por correo al iniciar sesión desde un navegador/sistema no visto en `SESSION_HISTORY_DAYS` |
| `SESSION_HISTORY_DAYS` | 180 | Historial de sesiones conservado |
| `ACCOUNT_INACTIVITY_DISABLE_DAYS` | 90 | Cuentas sin iniciar sesión en N días se desactivan (0 = nunca; nunca el último `SUPER_ADMIN`) |
| `AUDIT_RETENTION_DAYS` | 0 | Retención de la bitácora (0 = indefinida; mínimo efectivo 365). Cada purga queda registrada |

Cada inicio de sesión queda registrado como **sesión** (dispositivo, IP, última
actividad). El titular puede cerrar sesiones sueltas en *Seguridad de la cuenta*, y
`ADMIN_SEGURIDAD` en *Usuarios y accesos*. Cerrar una sesión invalida de inmediato
sus tokens sin afectar a las demás.

### 4.2 Sesiones y cola de correos

| Variable | Default | Efecto |
|---|---|---|
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 15 | Vida del access token (en memoria del navegador) |
| `SESSION_IDLE_TIMEOUT_MINUTES` | 30 | Inactividad máxima **aplicada por el servidor**. Debe ser > access. El frontend usa el mismo valor (build arg) |
| `SESSION_ABSOLUTE_MAX_HOURS` | 12 | Duración máxima de una sesión desde el login, aunque haya actividad |
| `REFRESH_COOKIE_PERSISTENT` | false | `false` = la sesión muere al cerrar el navegador |
| `REFRESH_REUSE_GRACE_SECONDS` | 30 | Reusar un refresh ya rotado fuera de esta ventana se trata como robo: se cierran **todas** las sesiones del usuario (auditoría `REFRESH_TOKEN_REUSE`) |
| `OUTBOX_MAX_ATTEMPTS` | 7 | Reintentos de un correo (1m, 5m, 15m, 1h, 3h, 6h…) antes de marcarlo `FALLIDO` |
| `OUTBOX_RETENTION_DAYS` | 30 | Días que se conservan los correos ya enviados |

Los correos se guardan en la tabla `SYS_EMAIL_OUTBOX` y los envía un worker en
cada proceso del backend, así que **no se pierden si el SMTP cae o el backend se
reinicia**. Para ver o reintentar la cola: `GET /api/v1/gov/email-outbox` y
`POST /api/v1/gov/email-outbox/reintentar` (SUPER_ADMIN). En `/metrics` aparece
`inv_email_outbox{estado="FALLIDO"}`, que conviene alertar si es mayor que 0. Los
correos de restablecimiento de contraseña y los códigos 2FA **no** se guardan en la
cola, porque contienen secretos; se envían directamente.

Tareas periódicas incluidas (no requieren cron): purga de tokens revocados,
claves de idempotencia, códigos 2FA y correos antiguos (cada 6 h), y la
sincronización con AD si está activa. Con varios workers, un lock en Redis
garantiza que cada tarea corre una sola vez por intervalo.

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
docker compose up -d --build              # migrator one-shot; backend arranca solo si termina bien
```

---

## 9. Empezar completamente de cero (borrar TODO)

> ⚠️ Destruye la base de datos y los adjuntos. Úsalo solo si quieres un entorno virgen.

```bash
cd inventario-ti-backend/deploy
docker compose down -v        # -v elimina los volúmenes (postgres_data, adjuntos_data, caddy_*)
docker compose up -d --build  # migrator crea esquema + sa + seed mínimo; luego inicia HTTP
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
- [ ] Log de arranque con `rls.db_layer_active` (capa RLS de PostgreSQL activa, §4.4).
- [ ] Cada cuenta de inventario restringida a sus sedes; alcance global solo donde sea imprescindible.
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
