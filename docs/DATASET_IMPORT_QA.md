# QA - Importacion de dataset de inventario

Fecha de ejecucion: 2026-07-06

## Alcance

Se analizaron e importaron los HTML de `C:\Lombardi\codigo\dataset` hacia la produccion local del sistema.

La utilidad agregada es:

```bash
python -m app.seed_dataset_inventory --dataset /tmp/dataset --dry-run
python -m app.seed_dataset_inventory --dataset /tmp/dataset
```

## Resultado de carga

- Archivos HTML procesados: 41
- Activos cargados por hostname: 41
- Personas nominales creadas/actualizadas: 26
- Persona tecnica de staging: 1
- Movimientos de custodia abiertos: 41
- Especificaciones tecnicas cargadas: 1025
- Duplicados de hostname: 0
- Duplicados de serie: 0

Distribucion:

- Laptop: 32
- Desktop: 7
- Workstation: 2
- Marca normalizada: HP, 41 equipos

Sistemas operativos detectados:

- Microsoft Windows 10 Pro (21H2): 10
- Microsoft Windows 10 Pro (22H2): 21
- Microsoft Windows 11 Pro (25H2): 8
- Microsoft Windows 11 Pro (24H2): 1
- Microsoft Windows 11 Pro (22H2): 1

## Validaciones ejecutadas

- Dry-run transaccional: OK
- Carga real: OK
- Reejecucion idempotente: OK, no duplica registros
- Primaria transaccional: 41 activos, 41 movimientos abiertos, 1025 especificaciones
- Replica de lectura/reporteria: 41 activos, 41 movimientos abiertos, 1025 especificaciones
- `pg_is_in_recovery()`:
  - primaria: `false`
  - replica de lectura: `true`
- Duplicados de movimientos abiertos por activo: 0
- Duplicados de serie en dataset importado: 0
- Health extendido: DB, replica y Redis en `ok`

Endpoints validados:

- `GET /api/v1/core/activos/by-code/NBPE01001`: 200
- `GET /api/v1/core/activos/{id}/especificaciones`: 200, 25 specs
- `POST /api/v1/core/activos/search`: 200, busqueda por hostname devuelve 1
- `GET /api/v1/trazabilidad/activo/{id}/historial`: 200, custodia vigente visible
- `POST /api/v1/core/activos/etiquetas.pdf`: 200, PDF generado solo para codigos seleccionados

## Mapeo aplicado

- `ACT_Codigo_Interno`: hostname del equipo.
- `ACT_Serie_Fabricante`: numero de serie del HTML.
- `ACT_Hostname`: hostname del HTML.
- Marca `Hewlett-Packard`: normalizada a `HP`.
- Tipos:
  - `NBPE*` -> Laptop
  - `PCPE*` -> Desktop
  - `WKSPE*` / `WKSP*` -> Workstation
- Custodia:
  - Usuarios nominales se crean como personas con email sintetico `@lombardi.dataset.local`.
  - Usuarios genericos se asignan a `TI Staging`.
- Especificaciones:
  - RAM, almacenamiento, procesador, sistema operativo, TPM, Windows 11, TeamViewer, MAC principal, discos, red, video, agentes, fuente del inventario.

## Observaciones QA

1. El dataset no trae fecha real de compra. Como `INV_ACTIVO.ACT_Fecha_Compra` es obligatorio, se uso la fecha del reporte de inventario y se guardo la fuente en especificaciones. Para inventario financiero profesional, el dataset debe incorporar fecha de compra, garantia y costo real o el modelo debe separar `fecha_inventario` de `fecha_compra`.

2. Hay 15 hostnames con usuario generico (`Lombardilatino`, `inge.pe`, `pivote*`). Se cargaron bajo custodia `TI Staging` para no simular propietarios finales. Requieren validacion operativa.

3. El EAV de especificaciones limita `ESP_Valor` a 255 caracteres. Para hardware detallado se guardaron resumenes profesionales, pero no todas las filas crudas de discos/red/perfiles. Si el objetivo es auditoria tecnica completa, conviene agregar una tabla/JSONB de inventario tecnico bruto por activo.

4. TeamViewer ID y MAC principal son datos sensibles de operacion. Deben mantenerse visibles solo para roles autorizados; si el rol `CONSULTA` no necesita soporte remoto, la UI deberia ocultarlos o enmascararlos.

5. Implementado el 2026-07-06: con 25 especificaciones por activo, la vista de detalle agrupa la informacion en secciones: Resumen operativo, Hardware, Sistema, Seguridad, Red y Fuente. La UI evita lista plana, muestra nombres de catalogo y permite que textos largos envuelvan sin scroll horizontal.

## Estado

La data real queda cargada y es trazable: cada equipo tiene activo, serie, specs, persona/custodia, area, movimiento vigente y evento de auditoria de importacion.
