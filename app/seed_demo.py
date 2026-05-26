"""
Seed completo de demo: catálogos + ubicaciones + organización + activos +
licencias + asignaciones + mantenimientos.

Idempotente: si detecta que ya existen catálogos básicos (Marcas con >= 3 items),
salta toda la siembra.

Uso:
    docker exec lombardi-backend-1 python -m app.seed_demo
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.core.security import get_password_hash
from app.db.session import SessionLocal
from app.models.catalogs import (
    EstadoOperativo, Marca, Modelo, TipoActivo, TipoConexion, TipoEspecificacion,
)
from app.models.core import Activo, Especificacion
from app.models.governance import ConfiguracionSistema, Secuencia
from app.models.location import Area, Edificio, Estado, Municipio, Nivel, Pais, Sede
from app.models.organization import Cargo, Departamento, Persona, Usuario
from app.models.software import Instalacion, Licencia, Software, TipoLicencia
from app.models.traceability import (
    DetalleMantenimiento, Mantenimiento, Movimiento,
    TipoEvidencia, TipoMantenimiento, TipoMovimiento,
)


logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("seed")


async def seed_demo() -> None:
    async with SessionLocal() as db:
        # Idempotencia: si ya hay catálogos cargados, omite
        count = (await db.execute(select(func.count()).select_from(Marca))).scalar() or 0
        if count >= 3:
            log.info("Seed demo: catálogos ya cargados (Marcas=%d). Omito.", count)
            return

        log.info("==> Configuración del sistema (branding)")
        cfg = (await db.execute(select(ConfiguracionSistema).where(
            ConfiguracionSistema.SYS_Configuracion == 1
        ))).scalar_one_or_none()
        if cfg is None:
            cfg = ConfiguracionSistema(SYS_Configuracion=1)
            db.add(cfg)
        cfg.SYS_Nombre_Empresa = "Lombardi"
        cfg.SYS_Color_Primario = "#0ea5e9"
        cfg.SYS_Color_Secundario = "#22c55e"
        # Logo via dummyimage.com (https estable, sin hotlink-protection).
        cfg.SYS_Logo_URL = "https://dummyimage.com/200x60/0ea5e9/ffffff.png&text=Lombardi"
        cfg.SYS_Idioma_Defecto = "es"

        # ===== CATÁLOGOS =====
        log.info("==> Catálogos técnicos")
        tipos_activo = [
            TipoActivo(TAC_Nombre="Laptop", TAC_Prefijo="LPT"),
            TipoActivo(TAC_Nombre="Desktop", TAC_Prefijo="PC"),
            TipoActivo(TAC_Nombre="Monitor", TAC_Prefijo="MON"),
            TipoActivo(TAC_Nombre="Teclado", TAC_Prefijo="TEC"),
            TipoActivo(TAC_Nombre="Mouse", TAC_Prefijo="MSE"),
            TipoActivo(TAC_Nombre="Servidor", TAC_Prefijo="SRV"),
            TipoActivo(TAC_Nombre="Impresora", TAC_Prefijo="IMP"),
            TipoActivo(TAC_Nombre="Tablet", TAC_Prefijo="TBT"),
        ]
        db.add_all(tipos_activo)

        marcas = [
            Marca(MAR_Nombre="Dell"),
            Marca(MAR_Nombre="HP"),
            Marca(MAR_Nombre="Lenovo"),
            Marca(MAR_Nombre="Apple"),
            Marca(MAR_Nombre="Logitech"),
            Marca(MAR_Nombre="Samsung"),
            Marca(MAR_Nombre="LG"),
        ]
        db.add_all(marcas)

        tipos_conexion = [
            TipoConexion(TCN_Nombre="USB", TCN_Descripcion="Universal Serial Bus"),
            TipoConexion(TCN_Nombre="HDMI", TCN_Descripcion="High-Definition Multimedia"),
            TipoConexion(TCN_Nombre="DisplayPort"),
            TipoConexion(TCN_Nombre="Bluetooth"),
            TipoConexion(TCN_Nombre="Ethernet"),
            TipoConexion(TCN_Nombre="VGA"),
        ]
        db.add_all(tipos_conexion)

        estados = [
            EstadoOperativo(EOP_Nombre="Disponible", EOP_Descripcion="Listo para asignación"),
            EstadoOperativo(EOP_Nombre="Asignado", EOP_Descripcion="En uso por una persona"),
            EstadoOperativo(EOP_Nombre="En Reparación", EOP_Descripcion="Mantenimiento abierto"),
            EstadoOperativo(EOP_Nombre="Baja", EOP_Descripcion="Fuera de inventario"),
            EstadoOperativo(EOP_Nombre="En Bodega", EOP_Descripcion="Almacenado sin asignar"),
        ]
        db.add_all(estados)

        tipos_espec = [
            TipoEspecificacion(TES_Nombre="RAM", TES_Unidad_Medida="GB"),
            TipoEspecificacion(TES_Nombre="Almacenamiento", TES_Unidad_Medida="GB"),
            TipoEspecificacion(TES_Nombre="Procesador"),
            TipoEspecificacion(TES_Nombre="Tarjeta Gráfica"),
            TipoEspecificacion(TES_Nombre="Sistema Operativo"),
            TipoEspecificacion(TES_Nombre="Tamaño Pantalla", TES_Unidad_Medida="pulgadas"),
        ]
        db.add_all(tipos_espec)

        await db.flush()

        # Modelos
        modelos = [
            Modelo(MOD_Nombre="Latitude 7430", MOD_Anio_Lanzamiento=2023,
                   MAR_Marca=marcas[0].MAR_Marca),  # Dell
            Modelo(MOD_Nombre="OptiPlex 7090", MOD_Anio_Lanzamiento=2022,
                   MAR_Marca=marcas[0].MAR_Marca),  # Dell
            Modelo(MOD_Nombre="EliteBook 840", MOD_Anio_Lanzamiento=2023,
                   MAR_Marca=marcas[1].MAR_Marca),  # HP
            Modelo(MOD_Nombre="ThinkPad X1 Carbon", MOD_Anio_Lanzamiento=2024,
                   MAR_Marca=marcas[2].MAR_Marca),  # Lenovo
            Modelo(MOD_Nombre="MacBook Pro 14", MOD_Anio_Lanzamiento=2024,
                   MAR_Marca=marcas[3].MAR_Marca),  # Apple
            Modelo(MOD_Nombre="MX Master 3S", MOD_Anio_Lanzamiento=2023,
                   MAR_Marca=marcas[4].MAR_Marca,
                   TCN_Tipo_Conexion=tipos_conexion[0].TCN_Tipo_Conexion),  # Logitech USB
            Modelo(MOD_Nombre="UltraSharp U2722D", MOD_Anio_Lanzamiento=2023,
                   MAR_Marca=marcas[0].MAR_Marca,
                   TCN_Tipo_Conexion=tipos_conexion[1].TCN_Tipo_Conexion),  # Dell HDMI
        ]
        db.add_all(modelos)
        await db.flush()

        # ===== UBICACIÓN GEOGRÁFICA =====
        log.info("==> Ubicaciones (GT/MX)")
        gt = Pais(PAI_Nombre="Guatemala", PAI_Codigo_ISO="GT")
        mx = Pais(PAI_Nombre="México", PAI_Codigo_ISO="MX")
        db.add_all([gt, mx])
        await db.flush()

        estado_gt = Estado(EST_Nombre="Guatemala", PAI_Pais=gt.PAI_Pais)
        estado_jal = Estado(EST_Nombre="Jalisco", PAI_Pais=mx.PAI_Pais)
        db.add_all([estado_gt, estado_jal])
        await db.flush()

        muni_gt = Municipio(MUN_Nombre="Guatemala", EST_Estado=estado_gt.EST_Estado)
        muni_gdl = Municipio(MUN_Nombre="Guadalajara", EST_Estado=estado_jal.EST_Estado)
        db.add_all([muni_gt, muni_gdl])
        await db.flush()

        sede_central = Sede(
            SED_Nombre="Sede Central",
            SED_Direccion_Calle="Avenida Reforma",
            SED_Direccion_Numero="9-55 Zona 10",
            MUN_Municipio=muni_gt.MUN_Municipio,
        )
        sede_gdl = Sede(
            SED_Nombre="Sede Guadalajara",
            SED_Direccion_Calle="Av. Vallarta",
            SED_Direccion_Numero="1234",
            MUN_Municipio=muni_gdl.MUN_Municipio,
        )
        db.add_all([sede_central, sede_gdl])
        await db.flush()

        edif_a = Edificio(EDI_Nombre="Torre A", SED_Sede=sede_central.SED_Sede)
        edif_b = Edificio(EDI_Nombre="Torre B", SED_Sede=sede_central.SED_Sede)
        edif_gdl = Edificio(EDI_Nombre="Edificio Único", SED_Sede=sede_gdl.SED_Sede)
        db.add_all([edif_a, edif_b, edif_gdl])
        await db.flush()

        nivel_1a = Nivel(NIV_Numero_Piso="1", NIV_Alias="Recepción", EDI_Edificio=edif_a.EDI_Edificio)
        nivel_2a = Nivel(NIV_Numero_Piso="2", NIV_Alias="Oficinas", EDI_Edificio=edif_a.EDI_Edificio)
        nivel_3a = Nivel(NIV_Numero_Piso="3", NIV_Alias="TI", EDI_Edificio=edif_a.EDI_Edificio)
        nivel_b = Nivel(NIV_Numero_Piso="PB", NIV_Alias="Data Center", EDI_Edificio=edif_b.EDI_Edificio)
        nivel_gdl = Nivel(NIV_Numero_Piso="1", NIV_Alias="Principal", EDI_Edificio=edif_gdl.EDI_Edificio)
        db.add_all([nivel_1a, nivel_2a, nivel_3a, nivel_b, nivel_gdl])
        await db.flush()

        area_bodega = Area(ARE_Nombre="Bodega", ARE_Tipo_Acceso="Restringido", NIV_Nivel=nivel_1a.NIV_Nivel)
        area_oficinas = Area(ARE_Nombre="Oficinas Generales", NIV_Nivel=nivel_2a.NIV_Nivel)
        area_ti = Area(ARE_Nombre="Sala TI", ARE_Tipo_Acceso="Restringido", NIV_Nivel=nivel_3a.NIV_Nivel)
        area_dc = Area(ARE_Nombre="Site de Servidores", ARE_Tipo_Acceso="Restringido", NIV_Nivel=nivel_b.NIV_Nivel)
        area_gdl = Area(ARE_Nombre="Oficina Principal GDL", NIV_Nivel=nivel_gdl.NIV_Nivel)
        db.add_all([area_bodega, area_oficinas, area_ti, area_dc, area_gdl])
        await db.flush()

        # ===== ORGANIZACIÓN =====
        log.info("==> Organización (departamentos / cargos / personas)")
        dep_ti = Departamento(DEP_Nombre="Tecnología", DEP_Codigo_Costos="TI-100")
        dep_fin = Departamento(DEP_Nombre="Finanzas", DEP_Codigo_Costos="FIN-200")
        dep_rh = Departamento(DEP_Nombre="Recursos Humanos", DEP_Codigo_Costos="RH-300")
        dep_op = Departamento(DEP_Nombre="Operaciones", DEP_Codigo_Costos="OP-400")
        db.add_all([dep_ti, dep_fin, dep_rh, dep_op])

        cargo_ger = Cargo(CAR_Nombre="Gerente", CAR_Es_Jefatura=True)
        cargo_jefe = Cargo(CAR_Nombre="Jefe de Área", CAR_Es_Jefatura=True)
        cargo_analista = Cargo(CAR_Nombre="Analista")
        cargo_admin = Cargo(CAR_Nombre="Administrador TI")
        cargo_tec = Cargo(CAR_Nombre="Técnico de Soporte")
        cargo_aux = Cargo(CAR_Nombre="Auxiliar")
        db.add_all([cargo_ger, cargo_jefe, cargo_analista, cargo_admin, cargo_tec, cargo_aux])
        await db.flush()

        personas = [
            Persona(PER_Primer_Nombre="Carlos", PER_Primer_Apellido="Mendez",
                    PER_Email_Corporativo="cmendez@lombardi.demo",
                    DEP_Departamento=dep_ti.DEP_Departamento,
                    CAR_Cargo=cargo_ger.CAR_Cargo),
            Persona(PER_Primer_Nombre="María", PER_Primer_Apellido="García",
                    PER_Segundo_Apellido="López",
                    PER_Email_Corporativo="mgarcia@lombardi.demo",
                    PER_Telefono="+502 5555-1001",
                    DEP_Departamento=dep_fin.DEP_Departamento,
                    CAR_Cargo=cargo_jefe.CAR_Cargo),
            Persona(PER_Primer_Nombre="Jorge", PER_Primer_Apellido="Ramirez",
                    PER_Email_Corporativo="jramirez@lombardi.demo",
                    DEP_Departamento=dep_ti.DEP_Departamento,
                    CAR_Cargo=cargo_admin.CAR_Cargo),
            Persona(PER_Primer_Nombre="Ana", PER_Primer_Apellido="Torres",
                    PER_Email_Corporativo="atorres@lombardi.demo",
                    DEP_Departamento=dep_ti.DEP_Departamento,
                    CAR_Cargo=cargo_tec.CAR_Cargo),
            Persona(PER_Primer_Nombre="Luis", PER_Primer_Apellido="Hernandez",
                    PER_Email_Corporativo="lhernandez@lombardi.demo",
                    DEP_Departamento=dep_rh.DEP_Departamento,
                    CAR_Cargo=cargo_analista.CAR_Cargo),
            Persona(PER_Primer_Nombre="Sofia", PER_Primer_Apellido="Cruz",
                    PER_Email_Corporativo="scruz@lombardi.demo",
                    DEP_Departamento=dep_op.DEP_Departamento,
                    CAR_Cargo=cargo_analista.CAR_Cargo),
            Persona(PER_Primer_Nombre="Pedro", PER_Primer_Apellido="Vasquez",
                    PER_Email_Corporativo="pvasquez@lombardi.demo",
                    DEP_Departamento=dep_op.DEP_Departamento,
                    CAR_Cargo=cargo_aux.CAR_Cargo),
        ]
        db.add_all(personas)
        await db.flush()

        # Usuarios del sistema (vinculados a personas)
        # Reusa el usuario sa ya creado por init_prod.py
        db.add(Usuario(
            USU_Username="jramirez",
            USU_Password_Hash=get_password_hash("Lombardi#2026"),
            USU_Rol="ADMIN_TI",
            PER_Persona=personas[2].PER_Persona,
        ))
        db.add(Usuario(
            USU_Username="atorres",
            USU_Password_Hash=get_password_hash("Lombardi#2026"),
            USU_Rol="TECNICO",
            PER_Persona=personas[3].PER_Persona,
        ))
        db.add(Usuario(
            USU_Username="mgarcia",
            USU_Password_Hash=get_password_hash("Lombardi#2026"),
            USU_Rol="CONSULTA",
            PER_Persona=personas[1].PER_Persona,
        ))

        # ===== TIPOS PARA TRAZABILIDAD =====
        log.info("==> Catálogos de operación")
        tipos_mov = [
            TipoMovimiento(TMO_Nombre="Ingreso"),
            TipoMovimiento(TMO_Nombre="Asignación"),
            TipoMovimiento(TMO_Nombre="Devolución"),
            TipoMovimiento(TMO_Nombre="Préstamo"),
            TipoMovimiento(TMO_Nombre="Transferencia"),
        ]
        db.add_all(tipos_mov)

        tipos_mant = [
            TipoMantenimiento(TMA_Nombre="Preventivo"),
            TipoMantenimiento(TMA_Nombre="Correctivo"),
            TipoMantenimiento(TMA_Nombre="Predictivo"),
        ]
        db.add_all(tipos_mant)

        tipos_evi = [
            TipoEvidencia(TEV_Nombre="Fotografía"),
            TipoEvidencia(TEV_Nombre="Acta firmada"),
            TipoEvidencia(TEV_Nombre="Reporte técnico"),
        ]
        db.add_all(tipos_evi)
        await db.flush()

        # ===== ACTIVOS =====
        log.info("==> Activos")
        estado_disponible = estados[0]
        estado_asignado = estados[1]
        estado_bodega = estados[4]

        activos = [
            Activo(ACT_Codigo_Interno="LPT00001",
                   ACT_Serie_Fabricante="DELL-7430-001",
                   ACT_Hostname="LAP-CMENDEZ",
                   ACT_Fecha_Compra=date(2024, 1, 15),
                   ACT_Fin_Garantia=date(2027, 1, 15),
                   ACT_Costo=Decimal("18500.00"),
                   MOD_Modelo=modelos[0].MOD_Modelo,
                   TAC_Tipo_Activo=tipos_activo[0].TAC_Tipo_Activo,
                   EOP_Estado_Operativo=estado_asignado.EOP_Estado_Operativo),
            Activo(ACT_Codigo_Interno="LPT00002",
                   ACT_Serie_Fabricante="HP-840-001",
                   ACT_Hostname="LAP-MGARCIA",
                   ACT_Fecha_Compra=date(2024, 2, 10),
                   ACT_Fin_Garantia=date(2027, 2, 10),
                   ACT_Costo=Decimal("16800.00"),
                   MOD_Modelo=modelos[2].MOD_Modelo,
                   TAC_Tipo_Activo=tipos_activo[0].TAC_Tipo_Activo,
                   EOP_Estado_Operativo=estado_asignado.EOP_Estado_Operativo),
            Activo(ACT_Codigo_Interno="LPT00003",
                   ACT_Serie_Fabricante="LEN-X1C-001",
                   ACT_Hostname="LAP-JRAMIREZ",
                   ACT_Fecha_Compra=date(2024, 3, 5),
                   ACT_Fin_Garantia=date(2027, 3, 5),
                   ACT_Costo=Decimal("22000.00"),
                   MOD_Modelo=modelos[3].MOD_Modelo,
                   TAC_Tipo_Activo=tipos_activo[0].TAC_Tipo_Activo,
                   EOP_Estado_Operativo=estado_asignado.EOP_Estado_Operativo),
            Activo(ACT_Codigo_Interno="LPT00004",
                   ACT_Serie_Fabricante="APL-MBP14-001",
                   ACT_Hostname=None,
                   ACT_Fecha_Compra=date(2024, 6, 1),
                   ACT_Fin_Garantia=date(2025, 6, 1),
                   ACT_Costo=Decimal("38000.00"),
                   MOD_Modelo=modelos[4].MOD_Modelo,
                   TAC_Tipo_Activo=tipos_activo[0].TAC_Tipo_Activo,
                   EOP_Estado_Operativo=estado_bodega.EOP_Estado_Operativo),
            Activo(ACT_Codigo_Interno="PC00001",
                   ACT_Serie_Fabricante="DELL-7090-001",
                   ACT_Hostname="DSK-RECEP",
                   ACT_Fecha_Compra=date(2023, 9, 15),
                   ACT_Fin_Garantia=date(2026, 9, 15),
                   ACT_Costo=Decimal("12000.00"),
                   MOD_Modelo=modelos[1].MOD_Modelo,
                   TAC_Tipo_Activo=tipos_activo[1].TAC_Tipo_Activo,
                   EOP_Estado_Operativo=estado_disponible.EOP_Estado_Operativo),
            Activo(ACT_Codigo_Interno="MON00001",
                   ACT_Serie_Fabricante="DELL-U2722D-001",
                   ACT_Hostname=None,
                   ACT_Fecha_Compra=date(2024, 1, 20),
                   ACT_Fin_Garantia=date(2027, 1, 20),
                   ACT_Costo=Decimal("4500.00"),
                   MOD_Modelo=modelos[6].MOD_Modelo,
                   TAC_Tipo_Activo=tipos_activo[2].TAC_Tipo_Activo,
                   EOP_Estado_Operativo=estado_bodega.EOP_Estado_Operativo),
            Activo(ACT_Codigo_Interno="MSE00001",
                   ACT_Serie_Fabricante="LOG-MX3S-001",
                   ACT_Hostname=None,
                   ACT_Fecha_Compra=date(2024, 4, 1),
                   ACT_Fin_Garantia=date(2026, 4, 1),
                   ACT_Costo=Decimal("950.00"),
                   MOD_Modelo=modelos[5].MOD_Modelo,
                   TAC_Tipo_Activo=tipos_activo[4].TAC_Tipo_Activo,
                   EOP_Estado_Operativo=estado_bodega.EOP_Estado_Operativo),
        ]
        db.add_all(activos)
        await db.flush()

        # Sincronizar secuencias para que los próximos códigos
        # auto-generados no colisionen con los del seed.
        # LPT00001..LPT00004 ya usados -> secuencia LPT debe ir en 4.
        # PC00001 ya usado -> PC en 1. MON00001 -> 1. MSE00001 -> 1.
        sec_map = {"LPT": 4, "PC": 1, "MON": 1, "MSE": 1}
        for prefijo, ultimo in sec_map.items():
            db.add(Secuencia(
                SEC_Contexto=f"ASSET_{prefijo}",
                SEC_Ultimo_Numero=ultimo,
                SEC_Relleno=5,
            ))
        await db.flush()

        # Especificaciones técnicas para algunas laptops
        db.add_all([
            Especificacion(ESP_Valor="16", ACT_Activo=activos[0].ACT_Activo,
                           TES_Tipo_Especificacion=tipos_espec[0].TES_Tipo_Especificacion),
            Especificacion(ESP_Valor="512", ACT_Activo=activos[0].ACT_Activo,
                           TES_Tipo_Especificacion=tipos_espec[1].TES_Tipo_Especificacion),
            Especificacion(ESP_Valor="Intel Core i7-1265U", ACT_Activo=activos[0].ACT_Activo,
                           TES_Tipo_Especificacion=tipos_espec[2].TES_Tipo_Especificacion),
            Especificacion(ESP_Valor="Windows 11 Pro", ACT_Activo=activos[0].ACT_Activo,
                           TES_Tipo_Especificacion=tipos_espec[4].TES_Tipo_Especificacion),
            Especificacion(ESP_Valor="16", ACT_Activo=activos[2].ACT_Activo,
                           TES_Tipo_Especificacion=tipos_espec[0].TES_Tipo_Especificacion),
            Especificacion(ESP_Valor="1024", ACT_Activo=activos[2].ACT_Activo,
                           TES_Tipo_Especificacion=tipos_espec[1].TES_Tipo_Especificacion),
            Especificacion(ESP_Valor="Intel Core i7-1365U", ACT_Activo=activos[2].ACT_Activo,
                           TES_Tipo_Especificacion=tipos_espec[2].TES_Tipo_Especificacion),
            Especificacion(ESP_Valor="32", ACT_Activo=activos[3].ACT_Activo,
                           TES_Tipo_Especificacion=tipos_espec[0].TES_Tipo_Especificacion),
            Especificacion(ESP_Valor="1024", ACT_Activo=activos[3].ACT_Activo,
                           TES_Tipo_Especificacion=tipos_espec[1].TES_Tipo_Especificacion),
            Especificacion(ESP_Valor="Apple M3 Pro", ACT_Activo=activos[3].ACT_Activo,
                           TES_Tipo_Especificacion=tipos_espec[2].TES_Tipo_Especificacion),
        ])

        # ===== MOVIMIENTOS (asignaciones) =====
        log.info("==> Movimientos (asignaciones de activos a personas)")
        tipo_asig = tipos_mov[1]  # Asignación
        now = datetime.utcnow()
        db.add_all([
            Movimiento(
                ACT_Activo=activos[0].ACT_Activo,
                PER_Persona=personas[0].PER_Persona,
                ARE_Area=area_oficinas.ARE_Area,
                TMO_Tipo_Movimiento=tipo_asig.TMO_Tipo_Movimiento,
                MOV_Observacion="Asignación inicial — gerente TI",
                MOV_Fecha_Asignacion=now - timedelta(days=120),
            ),
            Movimiento(
                ACT_Activo=activos[1].ACT_Activo,
                PER_Persona=personas[1].PER_Persona,
                ARE_Area=area_oficinas.ARE_Area,
                TMO_Tipo_Movimiento=tipo_asig.TMO_Tipo_Movimiento,
                MOV_Observacion="Asignación — jefatura Finanzas",
                MOV_Fecha_Asignacion=now - timedelta(days=90),
            ),
            Movimiento(
                ACT_Activo=activos[2].ACT_Activo,
                PER_Persona=personas[2].PER_Persona,
                ARE_Area=area_ti.ARE_Area,
                TMO_Tipo_Movimiento=tipo_asig.TMO_Tipo_Movimiento,
                MOV_Observacion="Asignación — administrador TI",
                MOV_Fecha_Asignacion=now - timedelta(days=60),
            ),
        ])

        # ===== SOFTWARE / LICENCIAS =====
        log.info("==> Software y licencias")
        tipo_oem = TipoLicencia(TLI_Nombre="OEM", TLI_Descripcion="Pre-instalada en el equipo")
        tipo_vol = TipoLicencia(TLI_Nombre="Volumen", TLI_Descripcion="Licenciamiento por volumen")
        tipo_saas = TipoLicencia(TLI_Nombre="SaaS", TLI_Descripcion="Suscripción en la nube")
        db.add_all([tipo_oem, tipo_vol, tipo_saas])

        sw_win = Software(SOF_Nombre="Windows 11 Pro", SOF_Version="23H2", SOF_Fabricante="Microsoft")
        sw_office = Software(SOF_Nombre="Office 365 Business", SOF_Version="2024", SOF_Fabricante="Microsoft")
        sw_adobe = Software(SOF_Nombre="Acrobat DC", SOF_Version="2024", SOF_Fabricante="Adobe")
        sw_chrome = Software(SOF_Nombre="Chrome Enterprise", SOF_Version="125", SOF_Fabricante="Google")
        db.add_all([sw_win, sw_office, sw_adobe, sw_chrome])
        await db.flush()

        lic_win = Licencia(
            LIC_Cantidad_Total=50, LIC_Cantidad_Usada=3,
            LIC_Fecha_Vencimiento=date(2027, 12, 31),
            SOF_Software=sw_win.SOF_Software,
            TLI_Tipo_Licencia=tipo_vol.TLI_Tipo_Licencia,
        )
        lic_office = Licencia(
            LIC_Cantidad_Total=100, LIC_Cantidad_Usada=2,
            LIC_Fecha_Vencimiento=date(2026, 12, 31),
            SOF_Software=sw_office.SOF_Software,
            TLI_Tipo_Licencia=tipo_saas.TLI_Tipo_Licencia,
        )
        lic_adobe = Licencia(
            LIC_Cantidad_Total=10, LIC_Cantidad_Usada=0,
            LIC_Fecha_Vencimiento=date(2025, 12, 31),
            SOF_Software=sw_adobe.SOF_Software,
            TLI_Tipo_Licencia=tipo_saas.TLI_Tipo_Licencia,
        )
        db.add_all([lic_win, lic_office, lic_adobe])
        await db.flush()

        # Instalaciones
        db.add_all([
            Instalacion(ACT_Activo=activos[0].ACT_Activo,
                        LIC_Licencia=lic_win.LIC_Licencia,
                        INS_Fecha_Instalacion=date(2024, 1, 16)),
            Instalacion(ACT_Activo=activos[1].ACT_Activo,
                        LIC_Licencia=lic_win.LIC_Licencia,
                        INS_Fecha_Instalacion=date(2024, 2, 11)),
            Instalacion(ACT_Activo=activos[2].ACT_Activo,
                        LIC_Licencia=lic_win.LIC_Licencia,
                        INS_Fecha_Instalacion=date(2024, 3, 6)),
            Instalacion(ACT_Activo=activos[0].ACT_Activo,
                        LIC_Licencia=lic_office.LIC_Licencia,
                        INS_Fecha_Instalacion=date(2024, 1, 17)),
            Instalacion(ACT_Activo=activos[1].ACT_Activo,
                        LIC_Licencia=lic_office.LIC_Licencia,
                        INS_Fecha_Instalacion=date(2024, 2, 12)),
        ])

        # ===== MANTENIMIENTO de ejemplo (uno cerrado, uno abierto) =====
        log.info("==> Tickets de mantenimiento")
        mant_cerrado = Mantenimiento(
            ACT_Activo=activos[4].ACT_Activo,
            PER_Persona_Solicita=personas[5].PER_Persona,
            TMA_Tipo_Mantenimiento=tipos_mant[1].TMA_Tipo_Mantenimiento,  # Correctivo
            MAN_Descripcion_Falla="No enciende. Posible falla de fuente.",
            MAN_Fecha_Ingreso=now - timedelta(days=20),
            MAN_Fecha_Cierre=now - timedelta(days=15),
            MAN_Costo_Total=Decimal("850.00"),
        )
        db.add(mant_cerrado)
        await db.flush()
        db.add_all([
            DetalleMantenimiento(
                MAN_Mantenimiento=mant_cerrado.MAN_Mantenimiento,
                DMA_Accion_Realizada="Diagnóstico inicial",
                DMA_Costo_Item=Decimal("150.00"),
            ),
            DetalleMantenimiento(
                MAN_Mantenimiento=mant_cerrado.MAN_Mantenimiento,
                DMA_Accion_Realizada="Reemplazo de fuente de poder",
                DMA_Costo_Item=Decimal("700.00"),
            ),
        ])

        await db.commit()
        log.info("==> Seed demo: COMPLETADO.")
        log.info("    - Marcas: %d", len(marcas))
        log.info("    - Modelos: %d", len(modelos))
        log.info("    - Personas: %d", len(personas))
        log.info("    - Activos: %d", len(activos))
        log.info("    - Movimientos: 3 asignaciones activas")
        log.info("    - Mantenimiento: 1 ticket cerrado")
        log.info("    - Software: 4, Licencias: 3 (con instalaciones)")
        log.info("")
        log.info("USUARIOS DE DEMO (password = Lombardi#2026):")
        log.info("    sa          | SUPER_ADMIN  (password en .env)")
        log.info("    jramirez    | ADMIN_TI")
        log.info("    atorres     | TECNICO")
        log.info("    mgarcia     | CONSULTA")


if __name__ == "__main__":
    asyncio.run(seed_demo())
