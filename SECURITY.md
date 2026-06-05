# Runbook de Seguridad — Lombardi

Guía operativa de rotación de secretos y endurecimiento. Complementa los
cambios de código aplicados en la auditoría 2026-06-01.

## 1. Rotación de secretos

Los secretos del `.env` deben tratarse como **comprometidos** (estuvieron en
texto plano). Estado de rotación:

| Secreto | Rotado en código | Acción requerida del operador |
|---|---|---|
| `SECRET_KEY` | ✅ Sí (valor nuevo) | Ninguna — al desplegar, invalida JWTs (re-login). |
| `POSTGRES_PASSWORD` | ❌ No (rompería el volumen) | Ver §1.1. |
| `REDIS_PASSWORD` | ❌ No | Ver §1.2. |
| `SUPER_ADMIN_PASSWORD` | ❌ No (solo afecta bootstrap) | Ver §1.3. |
| `FIELD_ENCRYPTION_KEY` | ❌ No (rompería descifrado) | Ver §1.4 (MultiFernet). |

> No se rotaron automáticamente los que requieren coordinación con datos
> persistidos: cambiarlos a ciegas en el `.env` desincroniza el contenedor
> respecto del volumen y rompe el arranque.

### 1.1 Postgres
```bash
# 1) Genera una contraseña fuerte
NUEVA=$(python -c "import secrets;print(secrets.token_urlsafe(24))")
# 2) Cámbiala DENTRO de Postgres (con la contraseña vieja aún válida)
docker compose exec db psql -U invuser -d inventario \
  -c "ALTER USER invuser WITH PASSWORD '$NUEVA';"
# 3) Pon el mismo valor en .env (POSTGRES_PASSWORD) y recrea backend
#    (REDIS_URL/POSTGRES_PASSWORD se inyectan al backend)
docker compose up -d --force-recreate backend
```

### 1.2 Redis
```bash
NUEVA=$(python -c "import secrets;print(secrets.token_urlsafe(24))")
# Edita .env: REDIS_PASSWORD y REDIS_URL (redis://:$NUEVA@redis:6379/0)
docker compose up -d --force-recreate redis backend
```

### 1.3 Super admin
`SUPER_ADMIN_PASSWORD` solo se usa al crear el usuario en el primer bootstrap;
cambiarlo en `.env` después NO cambia la contraseña existente. Rótala vía API:
```bash
# Login como sa y usa el endpoint self-service
POST /api/v1/me/password { "current_password": "...", "new_password": "..." }
```
Esto además revoca todos los tokens del usuario.

### 1.4 Clave de cifrado de campos (Fernet) — rotación SIN downtime
`FIELD_ENCRYPTION_KEY` ahora admite **lista separada por comas**: la primera es
la primaria (cifra), las siguientes son legadas (solo descifran).
```bash
NUEVA=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
# .env: pon la nueva PRIMERA, la vieja DESPUÉS:
#   FIELD_ENCRYPTION_KEY=<NUEVA>,<VIEJA>
docker compose up -d --force-recreate backend
# (Opcional) re-cifrar registros existentes leyéndolos y re-guardándolos;
# cuando ya no queden valores con la clave vieja, elimínala del .env.
```

## 2. Migrar a un gestor de secretos (recomendado)

El `.env` en texto plano + inyección por variables de entorno (visible vía
`docker inspect` / `/proc/<pid>/environ`) es la brecha de fondo. Opciones:

- **Docker secrets** (swarm o compose): montar como `/run/secrets/*` y leerlos
  con `*_FILE`.
- **SOPS + age** o **git-crypt** para cifrar el `.env` en reposo.
- **HashiCorp Vault** / **AWS/GCP Secrets Manager** para entornos cloud.

## 3. Auditoría append-only

La migración `2025-12-13_auditoria_append_only` instala un trigger Postgres que
rechaza `UPDATE`/`DELETE` sobre `INV_AUDITORIA_SISTEMA`. Para purga por
retención hay que deshabilitar el trigger temporalmente con un rol privilegiado:
```sql
ALTER TABLE "INV_AUDITORIA_SISTEMA" DISABLE TRIGGER trg_auditoria_append_only;
DELETE FROM "INV_AUDITORIA_SISTEMA" WHERE "AUD_Fecha_Hora" < now() - interval '365 days';
ALTER TABLE "INV_AUDITORIA_SISTEMA" ENABLE TRIGGER trg_auditoria_append_only;
```
Para cumplimiento estricto: exportar periódicamente a almacenamiento WORM/SIEM.

## 4. Backups cifrados

`scripts/backup_db.sh` produce `gzip` sin cifrar (contiene PII). Cifra antes de
mover off-site y guárdalo SEPARADO de `FIELD_ENCRYPTION_KEY`:
```bash
gzip -c dump.sql | age -r <age-public-key> > dump.sql.gz.age
```

## 5. Verificación de dependencias (CI)
```bash
pip-audit -r backend/inventarioTI-backend/requirements.txt
```
