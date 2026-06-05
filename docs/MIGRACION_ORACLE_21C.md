# Migración a Oracle Database 21c — Viabilidad y cambios

## Veredicto

**Sí, es posible, con esfuerzo MODERADO.** El backend es muy portable porque:

- La capa ORM usa **tipos genéricos de SQLAlchemy** (`Uuid`, `JSON`, `Boolean`,
  `Numeric`, `Text`, `DateTime`, `Integer autoincrement`), **no** tipos PostgreSQL
  (`postgresql.UUID`, `JSONB`).
- Las consultas usan el **lenguaje de expresiones de SQLAlchemy** (portable), no SQL
  crudo de negocio.
- Los **UUID se generan en Python** (`default=uuid.uuid4`), sin depender de funciones de
  BD.
- Ya hay **bifurcación multi-motor** (flag `IS_SQLITE`, guardas `if dialect.name == "postgresql"`).
- **No** se usan tipos exóticos (ARRAY, INET, CITEXT, TSVECTOR, HSTORE, `DateTime(tz)`) ni
  operadores JSON (`->`, `->>`) ni regex (`~`).

Estimación: **~80% del código de aplicación migra sin tocarse.** El trabajo se concentra
en (1) driver/URI, (2) reescribir ~5 bloques de DDL crudo en migraciones, (3) un punto
realmente delicado: los **índices únicos parciales** que garantizan "un movimiento/
mantenimiento abierto por activo".

> **Nota:** Oracle 21c es la última versión *no* Long-Term-Support (su soporte premier
> terminó; 19c y 23ai son LTS). Si el objetivo es producción a largo plazo, conviene
> evaluar 23ai (que además tiene tipo `BOOLEAN` y `JSON` nativos, simplificando aún más).
> El análisis siguiente aplica igual a 21c y 23ai.

## Qué hay que cambiar (checklist)

### 1. Driver y conexión — esfuerzo BAJO
- Driver actual: `postgresql+psycopg` (psycopg 3) — `app/core/config.py` (~línea 165).
- **Cambio**: añadir una rama en `SQLALCHEMY_DATABASE_URI` que genere
  `oracle+oracledb://user:pwd@host:port/?service_name=...` usando **python-oracledb**
  (modo async, soportado por SQLAlchemy 2.0 + python-oracledb 2.x).
- `app/db/session.py`: los kwargs del pool (`pool_size`, `max_overflow`, `pool_recycle`,
  `pool_pre_ping`) son válidos en Oracle. Sin cambios.
- Añadir `oracledb` a `requirements.txt`.

### 2. Tipos de columna — esfuerzo BAJO (ORM) / regenerar DDL
- En el **ORM no hay nada que cambiar**: SQLAlchemy materializa `Uuid`→`RAW(16)`/
  `VARCHAR2`, `Boolean`→`NUMBER(1)`, `JSON`→`CLOB IS JSON` (o `JSON` nativo),
  `Text`→`CLOB`, `Numeric`→`NUMBER`, `Integer autoincrement`→`GENERATED AS IDENTITY`.
- El problema está en las **migraciones existentes**, que escribieron tipos PG nativos
  (`sa.UUID()`, `postgresql.JSONB`) en el DDL → ese DDL no es válido en Oracle y debe
  **regenerarse** (ver punto 6).

### 3. Trigger de auditoría append-only — esfuerzo BAJO-MEDIO
- `app/alembic/versions/2025-12-13_auditoria_append_only.py`: función + trigger
  **PL/pgSQL** que rechaza UPDATE/DELETE sobre `INV_AUDITORIA_SISTEMA` (ya protegido con
  `if dialect != postgresql: return`).
- **Oracle**: reescribir como trigger PL/SQL con `RAISE_APPLICATION_ERROR(-20001, '...')`
  (sin función separada).

### 4. Índices ÚNICOS PARCIALES — esfuerzo MEDIO (el punto crítico)
- `2025-12-08_endurecimiento_integridad.py`: `CREATE UNIQUE INDEX uq_movimiento_activo_abierto
  ... WHERE "MOV_Fecha_Devolucion" IS NULL` → garantiza **un solo movimiento abierto por
  activo** (defensa anti-condición de carrera junto con `FOR UPDATE`).
- `2025-12-14_concurrency_query_indexes.py`: equivalente para mantenimiento abierto.
- `2025-12-02_smart_indexes_optimization.py`: dos índices parciales **no únicos**.
- **Oracle 21c NO soporta `CREATE INDEX ... WHERE`.** Equivalente: **índice único
  function-based** que indexa la columna solo cuando se cumple la condición y `NULL` si no
  (Oracle no indexa filas todo-NULL):
  ```sql
  CREATE UNIQUE INDEX uq_mov_abierto ON "INV_MOVIMIENTO"
    (CASE WHEN "MOV_Fecha_Devolucion" IS NULL THEN "ACT_Activo" END);
  ```
  Reproduce exactamente la semántica "unicidad solo sobre filas abiertas". Es el cambio
  semántico más delicado; conviene un test específico de concurrencia tras migrar.

### 5. Upsert `ON CONFLICT` y otras sentencias crudas — esfuerzo MEDIO
- `INSERT ... ON CONFLICT DO NOTHING` en `2025-12-15_spec_types_bateria.py` y en
  `repositories/governance.py` (import `from sqlalchemy.dialects.postgresql import insert`).
  **Oracle**: `MERGE`, o `INSERT ... WHERE NOT EXISTS`, o try/except `IntegrityError`.
- `server_default=sa.text('now()')` literal → en Oracle `SYSTIMESTAMP`. (`func.now()` lo
  traduce SQLAlchemy solo; el `text('now()')` literal NO.)
- Identificadores CamelCase entre comillas dobles (`"ACT_Activo"`): válidos en Oracle pero
  **case-sensitive**; el ORM de SQLAlchemy los cita igual, así que DDL y ORM coinciden.
  Revisar caso por caso.

### 6. Migraciones Alembic — esfuerzo MEDIO-ALTO
Las 23 migraciones están escritas contra PostgreSQL (tipos `sa.UUID()`/`JSONB`, DDL PG,
guardas que hacen `return` en motores no-PG). **No son reutilizables tal cual** y, peor,
sus guardas dejarían a Oracle **sin** el trigger ni los índices únicos parciales.

**Recomendación**: generar un **baseline nuevo de migraciones para Oracle** —
autogenerar desde `Base.metadata` contra una BD Oracle vacía (`alembic revision
--autogenerate`) y **portar manualmente** los 5 bloques de DDL crudo (trigger, 2 índices
únicos parciales, 2 índices parciales no únicos, upsert de seed). Alembic **no traduce**
PL/pgSQL→PL/SQL ni índices parciales→function-based; eso es 100% manual.

### 7. Sin cambios (ya portable)
- `.ilike()` → SQLAlchemy lo emula con `LOWER() LIKE LOWER()` en Oracle (considerar
  índices function-based sobre `LOWER()` por rendimiento).
- `with_for_update()` / `FOR UPDATE` → idéntico en Oracle.
- `LIMIT/OFFSET` → `OFFSET/FETCH` automático.
- `func.now/coalesce/count/sum/max`, agregados, joins → portables.
- Tabla `SYS_SECUENCIA` (contador de negocio, no un SEQUENCE de PG) → portable.

## Tabla resumen

| Feature PostgreSQL | Equivalente Oracle 21c | Esfuerzo |
|---|---|---|
| Driver `postgresql+psycopg` / URI | `oracle+oracledb` (python-oracledb async) | Bajo |
| Tipos ORM (`Uuid`/`JSON`/`Boolean`/`Numeric`) | RAW/VARCHAR2, CLOB-IS-JSON, NUMBER | Bajo (auto) |
| `sa.UUID()` / `JSONB` en DDL de migración | regenerar DDL | Bajo |
| `Integer autoincrement` (SERIAL) | `GENERATED AS IDENTITY` | Bajo (auto) |
| `server_default text('now()')` | `SYSTIMESTAMP` | Bajo |
| `.ilike()` | `LOWER() LIKE LOWER()` | Bajo (auto) |
| `FOR UPDATE`, `LIMIT/OFFSET` | idéntico / `OFFSET FETCH` | Nulo |
| Trigger PL/pgSQL append-only | trigger PL/SQL `RAISE_APPLICATION_ERROR` | Bajo-Medio |
| `ON CONFLICT DO NOTHING` | `MERGE` / try-except | Medio |
| **Índices únicos parciales (`WHERE`)** | **índice único function-based (`CASE`)** | **Medio** |
| Reescritura de migraciones Alembic | baseline Oracle + portar 5 bloques DDL | Medio-Alto |

## Plan recomendado (alto nivel)

1. **Preparar entorno**: instancia Oracle 21c (o 23ai), usuario/esquema, `oracledb` en
   requirements, rama de URI en `config.py`.
2. **Baseline de esquema**: autogenerar migración Oracle desde `Base.metadata`; portar a
   mano el trigger, los índices únicos parciales (function-based) y el upsert de seed.
3. **Rama Oracle en 2 puntos de código**: el upsert `ON CONFLICT` del repositorio de
   gobernanza (MERGE/try-except) y cualquier `text('now()')` literal restante.
4. **Datos**: migrar datos existentes (ETL/`expdp`-`impdp` no aplica entre motores; usar
   un script de copia tabla a tabla respetando UUIDs y orden de FKs, o herramienta como
   Ora2Pg en sentido inverso / un dump CSV).
5. **Validar**: correr la suite (`pytest`) contra Oracle, con foco en el **test de
   concurrencia** del "movimiento abierto" y en integridad (409 vs 500). Verificar el
   trigger append-only rechazando UPDATE/DELETE.
6. **Rendimiento**: añadir índices function-based sobre `LOWER()` para las búsquedas
   `ilike`.

**Estimación global de esfuerzo**: días, no semanas, para un desarrollador con experiencia
en Oracle — dominado por (4) índices únicos parciales y (6) baseline de migraciones. El
código de negocio (endpoints/services/repositories) prácticamente no se toca.
