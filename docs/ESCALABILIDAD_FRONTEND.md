# Escalabilidad, seguridad y frontend

Fecha: 2026-07-06

## Backend: escalabilidad y base de datos

El backend queda preparado para dos pools de base de datos:

- Primario transaccional: `get_db`, usado por escrituras, autenticacion, cambios
  de estado, compras, asignaciones, offboarding, auditoria de cambios y
  migraciones.
- Replica de lectura: `get_read_db`, usada por reportería, dashboard, exports,
  auditoria consultiva, métricas y garantias.

Si no se configura una replica, `get_read_db` cae al primario, pero abre la
transaccion como `READ ONLY` en Postgres. Esto protege contra escrituras
accidentales desde endpoints de reporte.

### Garantias ACID

- Atomicidad: los servicios de escritura siguen controlando `commit` y
  `rollback` por caso de uso.
- Consistencia: las reglas de dominio y constraints siguen en el primario.
- Aislamiento: Postgres mantiene MVCC; los reportes en replica leen snapshots
  consistentes y no bloquean escrituras del primario.
- Durabilidad: el primario escribe WAL; la replica fisica aplica WAL en hot
  standby.

### Concurrencia

Los flujos criticos existentes deben mantenerse en el primario:

- Reservar cupos de licencia.
- Reservar/liberar claves individuales.
- Recepcion de ordenes.
- Asignacion/devolucion/transferencia de activos.
- Offboarding.
- Cambio de password, logout, revocacion de tokens y 2FA.

La replica no debe usarse para validaciones que preceden escrituras cuando se
requiere consistencia inmediata, porque puede existir replication lag.

### Variables relevantes

- `POSTGRES_REPLICA_SERVER`
- `POSTGRES_REPLICA_USER`
- `POSTGRES_REPLICA_PASSWORD`
- `POSTGRES_REPLICA_DB`
- `POSTGRES_REPLICA_PORT`
- `DB_READ_POOL_SIZE`
- `DB_READ_MAX_OVERFLOW`

En `docker-compose.yml`, la replica local se llama `db_report`.

## Frontend: tecnologias y versiones

Fuente: `codigo/inventarioTI-frontend/package.json`.

Runtime principal:

- React `^19.2.0`
- React DOM `^19.2.0`
- React Router DOM `^7.9.6`
- Material UI `^7.3.5`
- Emotion React `^11.14.0`
- Emotion Styled `^11.14.1`
- Axios `^1.13.2`
- React Hook Form `^7.66.1`
- Zod `^4.1.13`
- i18next `^25.6.3`
- react-i18next `^16.3.5`
- notistack `^3.0.2`
- jwt-decode `^4.0.0`
- Zustand `^5.0.8`

Tooling:

- Vite `^7.2.4`
- TypeScript `~5.9.3`
- ESLint `^9.39.1`
- typescript-eslint `^8.46.4`
- @vitejs/plugin-react `^5.1.1`

## Frontend: flujo de trabajo actual

### Arranque de aplicacion

1. `ConfigProvider` carga `/gov/config` antes del tema visual.
2. `ThemeProvider` construye el tema MUI con colores de configuracion.
3. `AuthProvider` intenta rehidratar sesion.
4. `BrowserRouter` monta rutas publicas y privadas.

### Autenticacion

1. Login interno o SSO.
2. Backend devuelve `access_token`.
3. El access token vive en memoria.
4. El refresh token vive solo en cookie `HttpOnly`.
5. `sessionStorage` guarda solo una marca no secreta de sesion activa.
6. Axios adjunta `Authorization: Bearer`.
7. Ante 401, Axios intenta refresh una sola vez y reintenta la request.
8. Si falla refresh, limpia sesion y redirige a `/login`.

### Autorizacion UI

`ProtectedRoute` valida roles:

- Operacion: `SUPER_ADMIN`, `ADMIN_TI`, `TECNICO`.
- Administracion/organizacion/compras/software: `SUPER_ADMIN`, `ADMIN_TI`.
- Configuracion global y auditoria: `SUPER_ADMIN`.

La seguridad real debe seguir en backend; el frontend solo mejora UX.

### Patron de modulo

Cada modulo suele tener:

- Pagina principal: `FeaturePage.tsx`.
- Dialogos de crear/editar/detalle.
- Servicio HTTP: `featureService.ts`.
- Tipos TS en `src/types`.
- Traducciones en `src/locales`.

Modulos principales:

- Dashboard.
- Activos.
- Scanner.
- Operaciones y trazabilidad.
- Software y licencias.
- Consumibles.
- Compras, proveedores, ordenes y garantias.
- Personas, departamentos y usuarios.
- Catalogos.
- Configuracion.
- Auditoria.

## Recomendaciones de refactor frontend

Prioridad alta:

- Code splitting por ruta con `React.lazy` para bajar el bundle inicial.
- Estandarizar data fetching y cache cliente. Opcion: TanStack Query, o un
  wrapper propio si se prefiere evitar una dependencia.
- Separar formularios complejos en hooks de dominio.
- Unificar tablas con paginacion, loading, empty state, error state y permisos.
- Revisar uso real de Zustand; si no se usa, retirarlo o adoptarlo para estado
  global no sensible.

Prioridad media:

- Definir convencion de errores UI por codigo backend.
- Aumentar pruebas frontend: smoke tests de rutas, auth, software/licencias,
  compras y offboarding.
- Agregar `manualChunks` en Vite para separar React/MUI/vendor.
- Crear contratos de API generados desde OpenAPI cuando el backend estabilice
  esquemas publicos.

Prioridad de seguridad:

- Mantener access token en memoria.
- Nunca guardar refresh token en JS.
- Evitar `dangerouslySetInnerHTML`.
- Mantener descarga/copia de claves de licencia en flujos auditados.
- Mantener role guards en UI, pero tratar backend como autoridad.
