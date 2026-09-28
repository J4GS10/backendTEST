# Auditoria de seguridad, integridad y flujo

Fecha: 2026-07-03

Este documento deja una base de validacion reproducible para probar el sistema en el
stack de produccion local (`https://localhost`) sin depender de datos demo inseguros.

## Alcance validado

- Seguridad: autenticacion interna, SSO hibrido, roles, 2FA, tokens revocados,
  politica de password, rate-limit y endpoints protegidos.
- Integridad: transacciones atomicas, rollback ante error, transiciones de estado,
  consistencia de movimientos, licencias y offboarding.
- Flujo: inventario, asignaciones, descargos, compras, garantias, software,
  consumibles, reparaciones, etiquetas QR, exportaciones y auditoria.
- Produccion local: servicios Docker levantados con Caddy, frontend, backend,
  PostgreSQL y Redis.

## Carga de registros de validacion

Ejecutar desde `C:\Lombardi`:

```powershell
docker compose exec backend python -m app.seed_validation
```

Propiedades del seed:

- Idempotente: se puede ejecutar mas de una vez sin duplicar registros.
- Seguro para produccion: no crea usuarios con passwords conocidas.
- Prefijo controlado: todos los registros funcionales se identifican con `VAL`.
- Trazable: registra un evento `VALIDATION_SEED` en auditoria del sistema.

## Registros para validar desde la UI

| Modulo | Buscar | Uso esperado |
|---|---|---|
| Empleados | `val.rrhh@lombardi.validation` | Receptor de RRHH para probar filtros por departamento y asignaciones. |
| Empleados | `val.ti@lombardi.validation` | Receptor tecnico para devoluciones, reparaciones y compras. |
| Empleados | `val.auditor@lombardi.validation` | Receptor externo para licenciamiento por persona. |
| Usuarios sistema | `val.tecnico.sso` | Usuario operador SSO Microsoft, inactivo y sin password local. |
| Usuarios sistema | `val.auditor.sso` | Usuario operador SSO Google, inactivo y sin password local. |
| Catalogos | `VAL Lenovo`, `VAL ThinkPad E14`, `VAL Laptop` | Validar marca, modelo, tipo de activo y prefijo de codigo automatico. |
| Ubicaciones | `VAL Area RRHH`, `VAL Area TI` | Validar asignacion contextual por area/departamento. |
| Activos | `VAL-LAP-001` | Activo asignado, custodia vigente, hostname `VAL-RRHH-LAP01`, garantia por vencer. |
| Activos | `VAL-LAP-002` | Activo en bodega con movimiento cerrado y garantia vencida. |
| Activos | `VAL-LAP-003` | Activo en reparacion con ticket abierto; no debe permitir asignacion logistica normal. |
| Activos | `VAL-MON-001` | Monitor disponible vinculado como componente hijo de `VAL-LAP-001`. |
| Activos | `VAL-MON-002`, `VAL-MON-003` | Dos activos de la misma linea de compra, con series diferentes y proveedor trazable. |
| Activos | Serie `VAL-SN-AUTO-001` | Activo creado por servicio para validar codigo automatico race-safe con prefijo `VLT`. |
| Consumibles | `VAL Toner HP 85A` | Stock actual 3, minimo 5; debe aparecer como bajo stock. |
| Compras | `VAL Proveedor Tecnologia` | Proveedor para validar ordenes y recepcion. |
| Compras | `VAL-OC-BORRADOR-0001` | Orden en borrador para validar recepcion sin doble captura. |
| Compras | `VAL-OC-RECIBIDA-0001` | Orden recibida en GTQ con lineas vinculadas a activo, consumible y licencia. |
| Compras | `VAL-OC-LOTE-CHF-0001` | Orden recibida en CHF con una linea de cantidad 2 y dos activos serializados. |
| Software | `VAL Suite Productividad` | Licencia total 5, usada 2; cinco claves individuales, tres disponibles. |
| Auditoria | `VALIDATION_SEED` | Evidencia inmutable de carga de datos de validacion. |

## Recorridos recomendados

1. Identidad: confirmar que empleados `VAL` no aparecen como operadores activos y que
   usuarios `VAL` de sistema no tienen password interna conocida.
2. Flujo unificado: crear o seleccionar `VAL Lenovo`, seleccionar `VAL ThinkPad E14`,
   registrar un activo nuevo y asignarlo a un empleado filtrado por departamento.
3. Asignacion: abrir `VAL-LAP-001`, revisar historial, custodia vigente, acta de
   entrega y exportacion en el idioma seleccionado.
4. Bloqueo de estado: intentar asignar `VAL-LAP-003`; el sistema debe bloquearlo por
   estar en reparacion.
5. Descargo: usar `VAL-LAP-002` para revisar historial cerrado y acta de descargo.
6. Garantias: revisar panel de garantias; `VAL-LAP-001` debe estar por vencer y
   `VAL-LAP-002` vencida.
7. Consumibles: revisar `VAL Toner HP 85A`; debe marcar bajo stock y mostrar dos
   movimientos.
8. Compras: revisar orden recibida `VAL-OC-RECIBIDA-0001`; sus lineas deben estar
   vinculadas a inventario, consumible y software sin recaptura manual.
9. Software: revisar `VAL Suite Productividad`; debe mostrar 2 usos activos de 5 y
   cinco claves individuales, con 3 disponibles.
10. Compras por lote: revisar `VAL-OC-LOTE-CHF-0001`; debe mostrar moneda CHF y
    trazabilidad de proveedor para `VAL-MON-002` y `VAL-MON-003`.
11. QR/etiquetas: generar etiquetas para activos `VAL` y escanear un QR para abrir la
    ficha, historial y acciones.
12. Auditoria: filtrar por `VALIDATION_SEED` y por cambios hechos durante la prueba;
    el historial no debe permitir eliminacion desde la UI.

## Evidencia tecnica ejecutada

Backend completo:

```powershell
cd C:\Lombardi\codigo\inventarioTI-backend
python -m pytest tests -q --tb=short --disable-warnings --log-cli-level=CRITICAL --log-level=CRITICAL
```

Resultado: `153 passed`.

Pruebas criticas de integridad:

```powershell
python -m pytest tests/test_acid_transactions.py tests/test_consistency.py tests/test_security_hardening.py tests/test_state_transitions.py -q --tb=short --disable-warnings --log-cli-level=CRITICAL --log-level=CRITICAL
```

Resultado: `28 passed`.

Verificacion de salud de produccion local:

```powershell
docker compose ps
curl.exe -k -sS https://localhost/health
```

Resultado esperado: backend, frontend, db y redis saludables; `/health` responde
`{"status":"ok","database":"ok","environment":"production"}`.

Verificacion directa de registros `VAL`:

```json
{
  "activos_VAL": 6,
  "activo_auto_VAL": 1,
  "personas_VAL": 3,
  "usuarios_sso_VAL": 2,
  "movimientos_VAL": 2,
  "movimientos_abiertos_VAL": 1,
  "tickets_abiertos_VAL": 1,
  "consumibles_VAL": 1,
  "movimientos_consumible_VAL": 2,
  "ordenes_VAL": 3,
  "ordenes_gtq_VAL": 2,
  "ordenes_chf_VAL": 1,
  "enlaces_lote_activos_VAL": 2,
  "software_VAL": 1,
  "licencias_claves_VAL": 5,
  "instalaciones_VAL": 2,
  "auditoria_validation_seed": ">= 1"
}
```

## Criterio de aceptacion

El sistema se considera listo para validacion funcional cuando:

- El stack responde por `https://localhost`.
- El backend mantiene la suite en verde.
- El frontend compila sin errores.
- Los registros `VAL` existen con los conteos anteriores.
- Las acciones bloqueadas por reglas de negocio fallan cerradas, no con errores
  genericos.
- Las operaciones que combinan cambios de activo, movimiento, licencia, hostname o
  compras se comportan de forma atomica: todo se guarda o todo se revierte.
