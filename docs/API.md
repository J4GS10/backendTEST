# Referencia de API — Sistema de Inventario TI

> **Base URL:** `/api/v1` (vía Caddy/Nginx). Autenticación: `Authorization: Bearer <access_token>` (JWT).
> Esta referencia se genera del esquema **OpenAPI** real del backend.
>
> **Docs interactivas (Swagger/ReDoc):** deshabilitadas en producción por seguridad
> (`app/main.py`). Para habilitarlas en un entorno no productivo, arranca el backend con
> `DEBUG=true` o `ENVIRONMENT=development` y visita `/api/v1/docs` (Swagger) o
> `/api/v1/redoc`. El JSON crudo está en `/api/v1/openapi.json`.
>
> **Regenerar esta referencia:**
> ```bash
> docker exec lombardi-backend-1 python -c "from app.main import app; import json; print(json.dumps(app.openapi()))" > openapi.json
> ```

## Convenciones
- **Roles:** `SUPER_ADMIN` ⊃ `ADMIN_TI` ⊃ `TECNICO`; `CONSULTA` = solo lectura.
  Ver la matriz completa en `backend/inventarioTI-backend/docs/RBAC_MATRIX.md`.
- **Errores:** `401` no autenticado · `403` sin permiso · `404` no existe ·
  `409` conflicto de integridad · `422` validación de entrada · `429` rate-limit.
- **Paginación:** `skip`/`limit` (tope `PAGINATION_MAX_LIMIT`). Búsquedas devuelven
  `{items, total, page, per_page}`.

---

## Operaciones por módulo

_Generado del esquema OpenAPI (v1.1.0, título: Sistema Inventario TI). 16 grupos, 203 operaciones, 139 schemas._

### Adjuntos (6)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/adjuntos/activos/{activo_id}` | List Adjuntos |
| `POST` | `/api/v1/adjuntos/activos/{activo_id}` | Upload Adjunto |
| `GET` | `/api/v1/adjuntos/ordenes/{orden_id}` | List Adjuntos Orden |
| `POST` | `/api/v1/adjuntos/ordenes/{orden_id}` | Upload Adjunto Orden |
| `DELETE` | `/api/v1/adjuntos/{id}` | Delete Adjunto |
| `GET` | `/api/v1/adjuntos/{id}/download` | Download Adjunto |

### Catálogos Técnicos (31)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/cat/estados-operativos` | List Estados Operativos |
| `POST` | `/api/v1/cat/estados-operativos` | Create Estado Operativo |
| `GET` | `/api/v1/cat/estados-operativos/{id}` | Get Estado Operativo |
| `PATCH` | `/api/v1/cat/estados-operativos/{id}` | Update Estado Operativo |
| `DELETE` | `/api/v1/cat/estados-operativos/{id}` | Delete Estado Operativo |
| `GET` | `/api/v1/cat/marcas` | List Marcas |
| `POST` | `/api/v1/cat/marcas` | Create Marca |
| `GET` | `/api/v1/cat/marcas/{id}` | Get Marca |
| `PATCH` | `/api/v1/cat/marcas/{id}` | Update Marca |
| `DELETE` | `/api/v1/cat/marcas/{id}` | Delete Marca |
| `POST` | `/api/v1/cat/modelos` | Create Modelo |
| `GET` | `/api/v1/cat/modelos` | List Modelos |
| `GET` | `/api/v1/cat/modelos-flat` | List Modelos Flat |
| `GET` | `/api/v1/cat/modelos/{id}` | Get Modelo |
| `PATCH` | `/api/v1/cat/modelos/{id}` | Update Modelo |
| `DELETE` | `/api/v1/cat/modelos/{id}` | Delete Modelo |
| `GET` | `/api/v1/cat/tipos-activo` | List Tipos Activo |
| `POST` | `/api/v1/cat/tipos-activo` | Create Tipo Activo |
| `GET` | `/api/v1/cat/tipos-activo/{id}` | Get Tipo Activo |
| `PATCH` | `/api/v1/cat/tipos-activo/{id}` | Update Tipo Activo |
| `DELETE` | `/api/v1/cat/tipos-activo/{id}` | Delete Tipo Activo |
| `GET` | `/api/v1/cat/tipos-conexion` | List Tipos Conexion |
| `POST` | `/api/v1/cat/tipos-conexion` | Create Tipo Conexion |
| `GET` | `/api/v1/cat/tipos-conexion/{id}` | Get Tipo Conexion |
| `PATCH` | `/api/v1/cat/tipos-conexion/{id}` | Update Tipo Conexion |
| `DELETE` | `/api/v1/cat/tipos-conexion/{id}` | Delete Tipo Conexion |
| `GET` | `/api/v1/cat/tipos-especificacion` | List Tipos Especificacion |
| `POST` | `/api/v1/cat/tipos-especificacion` | Create Tipo Especificacion |
| `GET` | `/api/v1/cat/tipos-especificacion/{id}` | Get Tipo Especificacion |
| `PATCH` | `/api/v1/cat/tipos-especificacion/{id}` | Update Tipo Especificacion |
| `DELETE` | `/api/v1/cat/tipos-especificacion/{id}` | Delete Tipo Especificacion |

### Compras y Garantías (12)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/compras/garantias` | List Garantias |
| `POST` | `/api/v1/compras/garantias/notificar` | Notificar Garantias |
| `GET` | `/api/v1/compras/ordenes` | List Ordenes |
| `POST` | `/api/v1/compras/ordenes` | Create Orden |
| `GET` | `/api/v1/compras/ordenes/{id}` | Get Orden |
| `PATCH` | `/api/v1/compras/ordenes/{id}/estado` | Cambiar Estado Orden |
| `POST` | `/api/v1/compras/ordenes/{id}/recibir` | Recibir Orden |
| `GET` | `/api/v1/compras/proveedores` | List Proveedores |
| `POST` | `/api/v1/compras/proveedores` | Create Proveedor |
| `GET` | `/api/v1/compras/proveedores/{id}` | Get Proveedor |
| `PATCH` | `/api/v1/compras/proveedores/{id}` | Update Proveedor |
| `DELETE` | `/api/v1/compras/proveedores/{id}` | Delete Proveedor |

### Consumibles (8)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/consumibles` | List Consumibles |
| `POST` | `/api/v1/consumibles` | Create Consumible |
| `GET` | `/api/v1/consumibles/{id}` | Get Consumible |
| `PATCH` | `/api/v1/consumibles/{id}` | Update Consumible |
| `DELETE` | `/api/v1/consumibles/{id}` | Delete Consumible |
| `POST` | `/api/v1/consumibles/{id}/entrada` | Registrar Entrada |
| `GET` | `/api/v1/consumibles/{id}/movimientos` | List Movimientos |
| `POST` | `/api/v1/consumibles/{id}/salida` | Registrar Salida |

### Core Inventario (10)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/core/activos` | Create Activo |
| `GET` | `/api/v1/core/activos` | List Activos |
| `POST` | `/api/v1/core/activos/search` | Search Activos |
| `PATCH` | `/api/v1/core/activos/{activo_id}` | Update Activo |
| `GET` | `/api/v1/core/activos/{activo_id}` | Get Activo Detail |
| `DELETE` | `/api/v1/core/activos/{activo_id}` | Delete Activo |
| `GET` | `/api/v1/core/activos/{activo_id}/especificaciones` | List Especificaciones |
| `POST` | `/api/v1/core/activos/{activo_id}/especificaciones` | Add Especificacion |
| `PATCH` | `/api/v1/core/especificaciones/{esp_id}` | Update Especificacion |
| `DELETE` | `/api/v1/core/especificaciones/{esp_id}` | Delete Especificacion |

### Exportación CSV (6)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/export/activos.csv` | Export Activos Csv |
| `GET` | `/api/v1/export/auditoria.csv` | Export Auditoria Csv |
| `GET` | `/api/v1/export/consumibles.csv` | Export Consumibles Csv |
| `GET` | `/api/v1/export/movimientos.csv` | Export Movimientos Csv |
| `GET` | `/api/v1/export/ordenes.csv` | Export Ordenes Csv |
| `GET` | `/api/v1/export/proveedores.csv` | Export Proveedores Csv |

### Ubicación Geográfica (36)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/geo/areas` | Create Area |
| `GET` | `/api/v1/geo/areas` | List Areas |
| `GET` | `/api/v1/geo/areas/all` | List All Areas Jerarquico |
| `GET` | `/api/v1/geo/areas/{id}` | Get Area |
| `PATCH` | `/api/v1/geo/areas/{id}` | Update Area |
| `DELETE` | `/api/v1/geo/areas/{id}` | Delete Area |
| `POST` | `/api/v1/geo/edificios` | Create Edificio |
| `GET` | `/api/v1/geo/edificios` | List Edificios |
| `GET` | `/api/v1/geo/edificios/{id}` | Get Edificio |
| `PATCH` | `/api/v1/geo/edificios/{id}` | Update Edificio |
| `DELETE` | `/api/v1/geo/edificios/{id}` | Delete Edificio |
| `POST` | `/api/v1/geo/estados` | Create Estado |
| `GET` | `/api/v1/geo/estados` | List Estados |
| `GET` | `/api/v1/geo/estados/{id}` | Get Estado |
| `PATCH` | `/api/v1/geo/estados/{id}` | Update Estado |
| `DELETE` | `/api/v1/geo/estados/{id}` | Delete Estado |
| `POST` | `/api/v1/geo/municipios` | Create Municipio |
| `GET` | `/api/v1/geo/municipios` | List Municipios |
| `GET` | `/api/v1/geo/municipios/{id}` | Get Municipio |
| `PATCH` | `/api/v1/geo/municipios/{id}` | Update Municipio |
| `DELETE` | `/api/v1/geo/municipios/{id}` | Delete Municipio |
| `POST` | `/api/v1/geo/niveles` | Create Nivel |
| `GET` | `/api/v1/geo/niveles` | List Niveles |
| `GET` | `/api/v1/geo/niveles/{id}` | Get Nivel |
| `PATCH` | `/api/v1/geo/niveles/{id}` | Update Nivel |
| `DELETE` | `/api/v1/geo/niveles/{id}` | Delete Nivel |
| `GET` | `/api/v1/geo/paises` | List Paises |
| `POST` | `/api/v1/geo/paises` | Create Pais |
| `GET` | `/api/v1/geo/paises/{id}` | Get Pais |
| `PATCH` | `/api/v1/geo/paises/{id}` | Update Pais |
| `DELETE` | `/api/v1/geo/paises/{id}` | Delete Pais |
| `POST` | `/api/v1/geo/sedes` | Create Sede |
| `GET` | `/api/v1/geo/sedes` | List Sedes |
| `GET` | `/api/v1/geo/sedes/{id}` | Get Sede |
| `PATCH` | `/api/v1/geo/sedes/{id}` | Update Sede |
| `DELETE` | `/api/v1/geo/sedes/{id}` | Delete Sede |

### Gobierno (5)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/gov/auditoria` | List Auditoria |
| `GET` | `/api/v1/gov/auditoria/resumen` | Auditoria Resumen |
| `GET` | `/api/v1/gov/config` | Get Config |
| `PUT` | `/api/v1/gov/config` | Update Config |
| `POST` | `/api/v1/gov/security/purge` | Purge Security Records |

### Autenticación (8)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/login/2fa/verify` | Verify 2Fa |
| `POST` | `/api/v1/login/access-token` | Login Access Token |
| `POST` | `/api/v1/login/logout` | Logout |
| `POST` | `/api/v1/login/password-reset/confirm` | Confirm Password Reset |
| `POST` | `/api/v1/login/password-reset/request` | Request Password Reset |
| `POST` | `/api/v1/login/refresh` | Refresh Access Token |
| `GET` | `/api/v1/me` | Me |
| `POST` | `/api/v1/me/password` | Change My Password |

### Mantenimiento y Soporte (14)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/mantenimiento/` | List Mantenimientos |
| `POST` | `/api/v1/mantenimiento/` | Registrar Mantenimiento |
| `PATCH` | `/api/v1/mantenimiento/detalles/{detalle_id}` | Update Detalle |
| `DELETE` | `/api/v1/mantenimiento/detalles/{detalle_id}` | Delete Detalle |
| `GET` | `/api/v1/mantenimiento/tipos` | List Tipos |
| `POST` | `/api/v1/mantenimiento/tipos` | Create Tipo |
| `GET` | `/api/v1/mantenimiento/tipos/{id}` | Get Tipo |
| `PATCH` | `/api/v1/mantenimiento/tipos/{id}` | Update Tipo |
| `DELETE` | `/api/v1/mantenimiento/tipos/{id}` | Delete Tipo |
| `GET` | `/api/v1/mantenimiento/{id}` | Get Mantenimiento |
| `DELETE` | `/api/v1/mantenimiento/{mantenimiento_id}` | Delete Mantenimiento |
| `PATCH` | `/api/v1/mantenimiento/{mantenimiento_id}/cerrar` | Cerrar Mantenimiento |
| `GET` | `/api/v1/mantenimiento/{mantenimiento_id}/detalles` | List Detalles |
| `POST` | `/api/v1/mantenimiento/{mantenimiento_id}/detalles` | Agregar Detalle |

### 2FA (7)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/me/2fa` | Get 2Fa Status |
| `POST` | `/api/v1/me/2fa/disable` | Disable 2Fa |
| `POST` | `/api/v1/me/2fa/email/activate` | Email Activate |
| `POST` | `/api/v1/me/2fa/email/setup` | Email Setup |
| `POST` | `/api/v1/me/2fa/recovery-codes/regenerate` | Regenerate Recovery Codes |
| `POST` | `/api/v1/me/2fa/totp/activate` | Totp Activate |
| `POST` | `/api/v1/me/2fa/totp/setup` | Totp Setup |

### Organización (24)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/org/cargos` | List Cargos |
| `POST` | `/api/v1/org/cargos` | Create Cargo |
| `GET` | `/api/v1/org/cargos/{id}` | Get Cargo |
| `PATCH` | `/api/v1/org/cargos/{id}` | Update Cargo |
| `DELETE` | `/api/v1/org/cargos/{id}` | Delete Cargo |
| `GET` | `/api/v1/org/departamentos` | List Departamentos |
| `POST` | `/api/v1/org/departamentos` | Create Departamento |
| `GET` | `/api/v1/org/departamentos/resumen` | Departamentos Resumen |
| `GET` | `/api/v1/org/departamentos/{id}` | Get Departamento |
| `PATCH` | `/api/v1/org/departamentos/{id}` | Update Departamento |
| `DELETE` | `/api/v1/org/departamentos/{id}` | Delete Departamento |
| `GET` | `/api/v1/org/departamentos/{id}/detalle` | Get Departamento Detalle |
| `GET` | `/api/v1/org/personas` | List Personas |
| `POST` | `/api/v1/org/personas` | Create Persona |
| `GET` | `/api/v1/org/personas/disponibles` | List Personas Disponibles |
| `GET` | `/api/v1/org/personas/{id}` | Get Persona |
| `PATCH` | `/api/v1/org/personas/{id}` | Update Persona |
| `DELETE` | `/api/v1/org/personas/{id}` | Delete Persona |
| `GET` | `/api/v1/org/usuarios` | List Usuarios |
| `POST` | `/api/v1/org/usuarios` | Create Usuario |
| `GET` | `/api/v1/org/usuarios/{id}` | Get Usuario |
| `PATCH` | `/api/v1/org/usuarios/{usuario_id}` | Update Usuario |
| `DELETE` | `/api/v1/org/usuarios/{usuario_id}` | Desactivar Usuario |
| `POST` | `/api/v1/org/usuarios/{usuario_id}/2fa/reset` | Reset Usuario 2Fa |

### Software y Licencias (18)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/soft/activos/{activo_id}/instalaciones` | List Instalaciones Activo |
| `POST` | `/api/v1/soft/instalaciones` | Registrar Instalacion |
| `POST` | `/api/v1/soft/instalaciones/desinstalar` | Desinstalar Software |
| `POST` | `/api/v1/soft/licencias` | Create Licencia |
| `GET` | `/api/v1/soft/licencias` | List Licencias |
| `GET` | `/api/v1/soft/licencias/{id}` | Get Licencia |
| `PATCH` | `/api/v1/soft/licencias/{id}` | Update Licencia |
| `DELETE` | `/api/v1/soft/licencias/{id}` | Delete Licencia |
| `GET` | `/api/v1/soft/software` | List Software |
| `POST` | `/api/v1/soft/software` | Create Software |
| `GET` | `/api/v1/soft/software/{id}` | Get Software |
| `PATCH` | `/api/v1/soft/software/{id}` | Update Software |
| `DELETE` | `/api/v1/soft/software/{id}` | Delete Software |
| `GET` | `/api/v1/soft/tipos-licencia` | List Tipos Licencia |
| `POST` | `/api/v1/soft/tipos-licencia` | Create Tipo Licencia |
| `GET` | `/api/v1/soft/tipos-licencia/{id}` | Get Tipo Licencia |
| `PATCH` | `/api/v1/soft/tipos-licencia/{id}` | Update Tipo Licencia |
| `DELETE` | `/api/v1/soft/tipos-licencia/{id}` | Delete Tipo Licencia |

### Dashboard y Métricas (1)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/stats/dashboard` | Get Dashboard Metrics |

### Trazabilidad (14)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/trazabilidad/acta/lote` | Descargar Acta Multiple |
| `GET` | `/api/v1/trazabilidad/acta/{movimiento_id}` | Descargar Acta |
| `GET` | `/api/v1/trazabilidad/activo/{activo_id}/historial` | Historial Activo |
| `POST` | `/api/v1/trazabilidad/devolucion` | Registrar Devolucion |
| `GET` | `/api/v1/trazabilidad/movimientos` | List Movimientos |
| `POST` | `/api/v1/trazabilidad/movimientos` | Registrar Movimiento |
| `GET` | `/api/v1/trazabilidad/persona/{persona_id}/asignaciones` | Get Asignaciones Persona |
| `POST` | `/api/v1/trazabilidad/persona/{persona_id}/offboarding` | Offboarding Persona |
| `GET` | `/api/v1/trazabilidad/tipos` | List Tipos |
| `POST` | `/api/v1/trazabilidad/tipos` | Create Tipo Movimiento |
| `GET` | `/api/v1/trazabilidad/tipos/{id}` | Get Tipo Movimiento |
| `PATCH` | `/api/v1/trazabilidad/tipos/{id}` | Update Tipo Movimiento |
| `DELETE` | `/api/v1/trazabilidad/tipos/{id}` | Delete Tipo Movimiento |
| `POST` | `/api/v1/trazabilidad/transferencia` | Registrar Transferencia |

### Health (3)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Health Check |
| `GET` | `/health/full` | Health Full |
| `GET` | `/metrics` | Metrics |
