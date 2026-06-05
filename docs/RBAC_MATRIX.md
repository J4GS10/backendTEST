# Matriz de control de acceso por rol (RBAC)

> Generado y verificado el 2026-06-05. Fuente de verdad: `app/api/deps.py`
> (`RoleChecker`) y las dependencias declaradas en cada router de
> `app/api/v1/endpoints/`. El router base aplica `Depends(get_current_user)`
> a todos los módulos de negocio (`org`, `geo`, `cat`, `core`, `trazabilidad`,
> `soft`, `mantenimiento`, `consumibles`, `adjuntos`, `compras`, `stats`,
> `export`); `login` y `gov` tienen reglas propias.

## Roles

| Rol | Incluido en | Capacidad |
|---|---|---|
| `SUPER_ADMIN` | `require_super_admin`, `require_admin`, `require_operativo` | Total. Único que ve auditoría, edita configuración global y purga seguridad. |
| `ADMIN_TI` | `require_admin`, `require_operativo` | Gestión completa de inventario, catálogos, personas, usuarios, compras. |
| `TECNICO` | `require_operativo` | Operación de campo: alta/edición de activos, asignaciones, mantenimientos, instalaciones. |
| `CONSULTA` | — (solo `get_current_user`) | **Solo lectura.** No pasa ningún `require_*`; por tanto no puede ejecutar ninguna operación de escritura. |

Atajos (`app/api/deps.py`):
- `require_super_admin = RoleChecker(["SUPER_ADMIN"])`
- `require_admin = RoleChecker(["SUPER_ADMIN", "ADMIN_TI"])`
- `require_operativo = RoleChecker(["SUPER_ADMIN", "ADMIN_TI", "TECNICO"])`

## Invariante verificado

**Cero endpoints mutadores (POST/PUT/PATCH/DELETE) sin guard de rol**, fuera del
autoservicio (`/me/password`, `/login/logout`, `/me/2fa/*`, reset de contraseña),
donde la identidad del propio usuario en el JWT es el control de acceso.
Verificación automatizada incluida en `scripts/check_rbac.py` (escanea los
decoradores y falla si algún mutador carece de `require_*`).

> Nota: `POST /core/activos/search` usa POST por llevar cuerpo de filtros, pero
> es de **lectura**; por diseño solo requiere autenticación.

## Matriz por módulo (operaciones de escritura)

| Módulo (prefijo) | Crear/Editar/Borrar catálogos y maestros | Operación de negocio | Borrado/decomiso | Solo SUPER_ADMIN |
|---|---|---|---|---|
| Catálogos (`/cat`) | `require_admin` | — | `require_admin` | — |
| Ubicación (`/geo`) | `require_admin` | — | `require_admin` | — |
| Organización (`/org`) | `require_admin` (deptos, cargos, personas, usuarios) | — | `require_admin` | — |
| Core inventario (`/core`) | `require_operativo` (activos, especificaciones) | `require_operativo` | **`require_admin`** (baja lógica de activo) | — |
| Trazabilidad (`/trazabilidad`) | `require_admin` (tipos) | `require_operativo` (movimiento, devolución, transferencia, actas) | **`require_admin`** (offboarding) | — |
| Software (`/soft`) | `require_admin` (software, licencias, tipos) | `require_operativo` (instalar/desinstalar) | `require_admin` | — |
| Mantenimiento (`/mantenimiento`) | `require_admin` (tipos) | `require_operativo` (registrar, cerrar, detalles) | `require_admin` | — |
| Consumibles (`/consumibles`) | `require_admin` (alta/edición) | `require_operativo` (entrada/salida de stock) | `require_admin` | — |
| Adjuntos (`/adjuntos`) | `require_operativo` (subir a activo) / `require_admin` (subir a orden) | — | `require_admin` | — |
| Compras (`/compras`) | `require_admin` (proveedores, órdenes) | `require_admin` (recibir, cambiar estado, notificar garantías) | `require_admin` | — |
| Exportación (`/export`) | — (solo GET) | `require_admin` (CSVs) | — | **`require_super_admin`** (`auditoria.csv`) |
| Gobierno (`/gov`) | — | — | — | **`require_super_admin`** (config, auditoría, purga) |

## Lecturas accesibles a `CONSULTA` (cualquier autenticado)

Los siguientes GET no exigen `require_*`, por lo que un usuario `CONSULTA`
(solo lectura) puede consultarlos. **Es una decisión de política de negocio**,
no un defecto: define qué información puede ver el rol de solo-consulta.

| Endpoint | Dato expuesto | ¿Restringir a `require_operativo`? |
|---|---|---|
| `GET /org/personas`, `/org/personas/disponibles` | PII (nombres, emails, teléfonos) | Decisión de negocio |
| `GET /compras/proveedores`, `/compras/ordenes` | Datos comerciales (montos, proveedores) | Decisión de negocio |
| `GET /trazabilidad/movimientos`, `/trazabilidad/persona/{id}/asignaciones` | Historial de asignaciones por persona | Decisión de negocio |
| `GET /consumibles/{id}/movimientos` | Historial de stock | Decisión de negocio |
| `GET /adjuntos/{id}/download` | Descarga de adjuntos (facturas, actas) | Decisión de negocio |

> Maestros y catálogos (`/cat/*`, `/geo/*`, departamentos, cargos) son
> vocabularios controlados y se consideran lectura abierta a cualquier
> autenticado por diseño.
