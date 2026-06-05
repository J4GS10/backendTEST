# Runbook: migración de PostgreSQL a Oracle Database 21c

> Guía **ejecutable** paso a paso. Para el análisis de viabilidad y la tabla resumen de
> incompatibilidades, ver [MIGRACION_ORACLE_21C.md](MIGRACION_ORACLE_21C.md).
>
> **Resumen**: ~80% del código no se toca. El trabajo real son 7 pasos: driver, URI,
> baseline de migraciones, 4 bloques de DDL portados a mano (trigger + 3 grupos de
> índices parciales), 1 rama de código (upsert de secuencia), datos y validación.
>
> **Recomendación de versión**: si es para producción a largo plazo, considera **Oracle
> 23ai** (LTS, con `BOOLEAN` y `JSON` nativos). Todo lo de aquí aplica a 21c y 23ai;
> donde difieren, se indica.

---

## Pre-requisitos

- Una instancia Oracle 21c (o 23ai) accesible. Para pruebas:
  `container-registry.oracle.com/database/free` o `gvenzl/oracle-free` (Docker).
- Un **esquema/usuario** dedicado para la app, con cuota y privilegios:
  ```sql
  CREATE USER inv_app IDENTIFIED BY "<password-fuerte>";
  GRANT CONNECT, RESOURCE, CREATE VIEW, CREATE SEQUENCE, CREATE TRIGGER TO inv_app;
  ALTER USER inv_app QUOTA UNLIMITED ON USERS;
  ```
- Cliente Oracle: **no** se necesita Instant Client si usas `python-oracledb` en **modo
  thin** (por defecto, Python puro). Solo se requiere Instant Client para modo "thick".

---

## Paso 1 — Dependencia del driver

En `backend/inventarioTI-backend/requirements.txt` añade:

```
oracledb>=2.2.0        # driver Oracle (python-oracledb), modo async + thin
```

`python-oracledb` 2.x soporta async con SQLAlchemy 2.0. Reconstruye la imagen del backend
al final (`docker compose build backend`).

---

## Paso 2 — Construcción de la URI (config.py)

Archivo: `app/core/config.py`, propiedad `SQLALCHEMY_DATABASE_URI` (~línea 158). Hoy es:

```python
@property
def SQLALCHEMY_DATABASE_URI(self) -> str:
    if self.POSTGRES_SERVER == "sqlite":
        return "sqlite+aiosqlite:///./inventario.db"
    encoded_password = quote_plus(self.POSTGRES_PASSWORD)
    return (
        f"postgresql+psycopg://{self.POSTGRES_USER}:{encoded_password}"
        f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    )
```

Añade una rama Oracle **antes** de la de Postgres (activada por un `DB_ENGINE=oracle` o por
convención de host). Ejemplo con una variable nueva `DB_ENGINE` (default `postgres`):

```python
@property
def SQLALCHEMY_DATABASE_URI(self) -> str:
    if self.POSTGRES_SERVER == "sqlite":
        return "sqlite+aiosqlite:///./inventario.db"
    encoded_password = quote_plus(self.POSTGRES_PASSWORD)
    if getattr(self, "DB_ENGINE", "postgres") == "oracle":
        # POSTGRES_DB se reutiliza como service_name de Oracle.
        return (
            f"oracle+oracledb://{self.POSTGRES_USER}:{encoded_password}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/?service_name={self.POSTGRES_DB}"
        )
    return (
        f"postgresql+psycopg://{self.POSTGRES_USER}:{encoded_password}"
        f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    )
```

Añade el campo y un flag de conveniencia:

```python
DB_ENGINE: str = "postgres"          # "postgres" | "oracle" | "sqlite"

@property
def IS_ORACLE(self) -> bool:
    return self.DB_ENGINE == "oracle"
```

> El puerto Oracle típico es **1521**. Pon `POSTGRES_PORT=1521`, `POSTGRES_DB=<service_name>`
> (p.ej. `FREEPDB1`), `POSTGRES_SERVER=<host>`, `DB_ENGINE=oracle` en el `.env`.

`app/db/session.py` no requiere cambios: los kwargs del pool (`pool_size`, `max_overflow`,
`pool_recycle`, `pool_pre_ping`) son válidos en Oracle.

---

## Paso 3 — Generar el baseline de esquema para Oracle

Las 23 migraciones actuales están escritas para Postgres (tipos `sa.UUID()`/`JSONB`, DDL
PG, guardas que hacen `return` en motores no-PG). **No se reutilizan**. Crea un baseline
nuevo autogenerado contra una BD Oracle vacía:

```bash
# Con el .env apuntando a Oracle (DB_ENGINE=oracle) y un esquema VACÍO:
docker exec lombardi-backend-1 alembic revision --autogenerate -m "baseline_oracle"
```

Alembic emitirá el DDL correcto para Oracle a partir de `Base.metadata`:
`Integer autoincrement → GENERATED AS IDENTITY`, `Uuid → RAW(16)`/`VARCHAR2`,
`Boolean → NUMBER(1)`, `JSON → CLOB (IS JSON)` (en 23ai, `JSON` nativo), `Text → CLOB`,
`Numeric → NUMBER`, `DateTime → DATE/TIMESTAMP`.

**Revisa el archivo generado** y verifica los tipos. Luego aplica:

```bash
docker exec lombardi-backend-1 alembic upgrade head
```

> Mantén el historial de Postgres y el de Oracle en ramas/branch_labels separadas, o
> trabaja el baseline Oracle en una rama de git dedicada. No mezcles ambos dialectos en una
> misma cadena de migraciones con `if dialect` (frágil).

---

## Paso 4 — Portar el trigger de auditoría append-only (PL/pgSQL → PL/SQL)

El original (`2025-12-13_auditoria_append_only.py`) usa PL/pgSQL. En la migración Oracle,
sustitúyelo por un trigger PL/SQL (no necesita función separada):

```python
# en la migración baseline_oracle (o una migración dedicada), upgrade():
op.execute("""
    CREATE OR REPLACE TRIGGER trg_auditoria_append_only
    BEFORE UPDATE OR DELETE ON "INV_AUDITORIA_SISTEMA"
    FOR EACH ROW
    BEGIN
        RAISE_APPLICATION_ERROR(-20001, 'INV_AUDITORIA_SISTEMA es append-only: operacion no permitida');
    END;
""")

# downgrade():
op.execute('DROP TRIGGER trg_auditoria_append_only')
```

Validación: un `UPDATE`/`DELETE` sobre `INV_AUDITORIA_SISTEMA` debe lanzar ORA-20001.

---

## Paso 5 — Portar los índices ÚNICOS PARCIALES (el punto crítico)

Oracle **no** soporta `CREATE INDEX ... WHERE`. Se reemplazan por **índices únicos
function-based** con `CASE`: indexan la clave solo cuando se cumple la condición y `NULL`
en caso contrario (Oracle no indexa filas con clave totalmente NULL → la unicidad solo
aplica a las filas "abiertas"). Garantizan exactamente la misma invariante.

### 5a. Un solo movimiento abierto por activo
Original (Postgres): `CREATE UNIQUE INDEX uq_movimiento_activo_abierto ON "INV_MOVIMIENTO"
("ACT_Activo") WHERE "MOV_Fecha_Devolucion" IS NULL`.

```sql
CREATE UNIQUE INDEX uq_movimiento_activo_abierto ON "INV_MOVIMIENTO"
  (CASE WHEN "MOV_Fecha_Devolucion" IS NULL THEN "ACT_Activo" END);
```

### 5b. Un solo mantenimiento abierto por activo
Original: índice único parcial con `WHERE "MAN_Fecha_Cierre" IS NULL`.

```sql
CREATE UNIQUE INDEX uq_mantenimiento_activo_abierto ON "INV_MANTENIMIENTO"
  (CASE WHEN "MAN_Fecha_Cierre" IS NULL THEN "ACT_Activo" END);
```

### 5c. Índices parciales NO únicos (rendimiento)
Originales: `ix_movimiento_activo_vigente WHERE "MOV_Fecha_Devolucion" IS NULL` y
`ix_instalacion_activa WHERE "INS_Estado" = true`. En Oracle, function-based (NO únicos);
nota que el booleano `true` → `1`:

```sql
CREATE INDEX ix_movimiento_activo_vigente ON "INV_MOVIMIENTO"
  (CASE WHEN "MOV_Fecha_Devolucion" IS NULL THEN "ACT_Activo" END);

CREATE INDEX ix_instalacion_activa ON "INV_INSTALACION"
  (CASE WHEN "INS_Estado" = 1 THEN "ACT_Activo" END);
```

Inclúyelos en la migración baseline con `op.execute(...)` en `upgrade()` y sus
`DROP INDEX` en `downgrade()`.

---

## Paso 6 — Rama de código: upsert de secuencia (ON CONFLICT)

Archivo: `app/repositories/governance.py` (~líneas 74-80). Hoy bifurca SQLite vs Postgres
y usa `on_conflict_do_nothing`. Oracle no tiene ese constructor en SQLAlchemy core. Añade
una rama Oracle con **MERGE** o, más simple y portable, con try/except sobre la
restricción única:

```python
# Patrón portable (sirve para cualquier motor): intentar insertar; si choca la unique,
# ignorar (otra transacción ya creó el contexto de secuencia).
from sqlalchemy.exc import IntegrityError
try:
    await self.db.execute(insert(Secuencia).values(SEC_Contexto=contexto, SEC_Valor=0))
    await self.db.flush()
except IntegrityError:
    await self.db.rollback()   # el contexto ya existe; continuar
```

> Si prefieres mantener el `on_conflict_do_nothing` para Postgres/SQLite por rendimiento,
> añade `elif settings.IS_ORACLE:` con el try/except de arriba.

Revisa también `2025-12-15_spec_types_bateria.py` (seed con `INSERT ... ON CONFLICT
("TES_Nombre") DO NOTHING`): en Oracle usa `MERGE` o reescribe el seed como upserts
idempotentes. Ese seed conviene moverlo a `init_prod.py`/`seed_demo.py` (que ya corren con
lógica idempotente) en vez de en la migración.

---

## Paso 7 — Migración de los DATOS existentes

`expdp/impdp` no aplica entre motores distintos. Opciones:

1. **Script de copia tabla a tabla** (recomendado, control total): leer de Postgres y
   escribir en Oracle respetando el **orden de las FKs** (catálogos → organización →
   ubicación → activos → movimientos → …) y **preservando los UUID** (se generan en
   Python, así que solo hay que copiarlos tal cual). Se puede hacer con un script que use
   las mismas sesiones SQLAlchemy contra ambas URIs.
2. **CSV intermedio**: `\copy` desde Postgres + `SQL*Loader`/`external tables` a Oracle.
3. **Ora2Pg** está pensado para Oracle→Postgres; para el sentido inverso, la opción 1 es
   más limpia.

Cuidados de datos:
- **Cadena vacía vs NULL**: Oracle trata `''` como `NULL`. Si hay columnas con cadenas
  vacías significativas, normalízalas (en este proyecto los strings vacíos no son
  semánticamente distintos de NULL, pero verifícalo).
- **Booleanos**: se almacenan como `NUMBER(1)` (0/1); SQLAlchemy lo gestiona en lectura.
- **JSON**: el snapshot de auditoría se guarda/lee completo (nunca se consulta por campo),
  así que `CLOB IS JSON` (21c) o `JSON` nativo (23ai) funcionan sin cambiar consultas.

---

## Paso 8 — Validación

```bash
# 1. Esquema + arranque
docker compose build backend && docker compose up -d backend
docker exec lombardi-backend-1 alembic current        # baseline_oracle (head)

# 2. Suite completa contra Oracle
docker exec lombardi-backend-1 python -m pytest tests/

# 3. Guard RBAC
docker exec lombardi-backend-1 python scripts/check_rbac.py
```

Pruebas manuales **críticas** (la semántica que cambió de motor):
- **Concurrencia "movimiento abierto"**: dos asignaciones simultáneas del mismo activo →
  una debe fallar con conflicto de unicidad (índice function-based 5a). Igual para
  mantenimiento (5b).
- **Auditoría append-only**: `UPDATE`/`DELETE` sobre `INV_AUDITORIA_SISTEMA` → ORA-20001.
- **Búsquedas `ilike`**: funcionan (SQLAlchemy emite `LOWER() LIKE LOWER()`); para
  rendimiento, crea índices function-based sobre `LOWER()` en columnas muy buscadas
  (nombre de persona, código/serie de activo):
  ```sql
  CREATE INDEX ix_persona_lower_nombre ON "INV_PERSONA" (LOWER("PER_Primer_Nombre"));
  ```
- **Integridad**: violar una unique/FK debe devolver **409**, no 500 (lo gestiona
  `commit_or_409`/`internal_error`, que ya mapea `IntegrityError`).

---

## Paso 9 — Cutover (puesta en producción)

1. Congelar escrituras en la BD Postgres (ventana de mantenimiento).
2. Ejecutar el script de copia de datos (Paso 7) y verificar conteos por tabla.
3. Cambiar el `.env` a Oracle (`DB_ENGINE=oracle`, host/puerto/service_name/credenciales).
4. `docker compose up -d --build backend` y validación (Paso 8).
5. Plan de rollback: mantener Postgres intacto y de solo-lectura hasta confirmar Oracle en
   producción; el cambio es solo de `.env` + imagen.

---

## Apéndice — Mapeo de tipos y checklist

| ORM / Postgres | Oracle 21c | Oracle 23ai |
|---|---|---|
| `Uuid` (gen en Python) | `RAW(16)` / `VARCHAR2(36)` | igual |
| `Integer autoincrement` | `GENERATED AS IDENTITY` | igual |
| `Boolean` | `NUMBER(1)` (0/1) | `BOOLEAN` nativo |
| `JSON` / `JSONB` | `CLOB` + `CHECK (col IS JSON)` | `JSON` nativo |
| `Text` | `CLOB` | igual |
| `Numeric(p,s)` | `NUMBER(p,s)` | igual |
| `DateTime` (naive) | `DATE` / `TIMESTAMP` | igual |
| `now()` server default | `SYSTIMESTAMP` | igual |
| índice parcial `WHERE` | índice function-based `CASE` | igual |
| `ON CONFLICT DO NOTHING` | `MERGE` / try-except | igual |
| `ilike` | `LOWER() LIKE LOWER()` (auto) | igual |
| `FOR UPDATE`, `OFFSET/FETCH` | idéntico (auto) | idéntico |

**Checklist de ejecución**
- [ ] `oracledb` en requirements; imagen reconstruida
- [ ] Rama Oracle en `config.py` (URI) + `DB_ENGINE`/`IS_ORACLE`
- [ ] Baseline de migraciones autogenerado y revisado
- [ ] Trigger append-only PL/SQL portado
- [ ] 3 índices function-based (5a, 5b, 5c) creados
- [ ] Rama del upsert de secuencia (governance.py) + seed de spec-types
- [ ] Datos copiados con orden de FKs y UUIDs preservados
- [ ] `pytest` verde contra Oracle + pruebas de concurrencia y append-only
- [ ] Índices `LOWER()` para búsquedas `ilike`
- [ ] Plan de cutover y rollback documentado
```
