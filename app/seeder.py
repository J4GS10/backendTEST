import asyncio
import logging
from datetime import date, datetime
from sqlalchemy import select, update
from app.db.session import SessionLocal
from app.core.security import get_password_hash

# ==========================================
# IMPORTACIÓN TOTAL DE MODELOS (32 ENTIDADES)
# ==========================================
from app.models.organization import Departamento, Cargo, Persona, Usuario
from app.models.location import Pais, Estado, Municipio, Sede, Edificio, Nivel, Area
from app.models.catalogs import TipoActivo, Marca, TipoConexion, Modelo, EstadoOperativo, TipoEspecificacion
from app.models.core import Activo, Especificacion
from app.models.traceability import TipoMovimiento, Movimiento, TipoMantenimiento, TipoEvidencia, Mantenimiento
from app.models.software import TipoLicencia, Software, Licencia, Instalacion
from app.models.governance import ConfiguracionSistema

# Configuración de Log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def seed_data():
    async with SessionLocal() as db:
        logger.info("🚀 INICIANDO SIEMBRA DE DATOS (PROTOCOL ENTERPRISE)...")

        # -------------------------------------------------------
        # 1. GOBIERNO (Configuración Singleton)
        # -------------------------------------------------------
        config = ConfiguracionSistema(
            SYS_Nombre_Empresa="TechCorp Global",
            SYS_Color_Primario="#0f172a",
            SYS_Idioma_Defecto="es"
        )
        db.add(config)

        # -------------------------------------------------------
        # 2. ORGANIZACIÓN (Actores)
        # -------------------------------------------------------
        logger.info("🔹 1. Creando Estructura Organizacional...")
        depto = Departamento(DEP_Nombre="Tecnología", DEP_Codigo_Costos="IT-2025")
        cargo_dev = Cargo(CAR_Nombre="Desarrollador Senior", CAR_Es_Jefatura=False)
        cargo_mgr = Cargo(CAR_Nombre="Gerente TI", CAR_Es_Jefatura=True)
        db.add_all([depto, cargo_dev, cargo_mgr]); await db.flush()

        # Actores Clave para tu prueba
        persona_juan = Persona(
            PER_Primer_Nombre="Juan", PER_Primer_Apellido="Perez", 
            PER_Email_Corporativo="juan@techcorp.com", 
            DEP_Departamento=depto.DEP_Departamento, CAR_Cargo=cargo_dev.CAR_Cargo
        )
        persona_pedro = Persona(
            PER_Primer_Nombre="Pedro", PER_Primer_Apellido="Gomez", 
            PER_Email_Corporativo="pedro@techcorp.com", 
            DEP_Departamento=depto.DEP_Departamento, CAR_Cargo=cargo_mgr.CAR_Cargo
        )
        db.add_all([persona_juan, persona_pedro]); await db.flush()

        # Usuario Admin (Login)
        usuario = Usuario(
            USU_Username="admin",
            USU_Password_Hash=get_password_hash("admin123"),
            USU_Salt="auto",
            USU_Rol="SUPER_ADMIN",
            PER_Persona=persona_juan.PER_Persona
        )
        db.add(usuario)

        # -------------------------------------------------------
        # 3. UBICACIÓN (Geo)
        # -------------------------------------------------------
        logger.info("🔹 2. Creando Mapa Geográfico...")
        pais = Pais(PAI_Nombre="Guatemala", PAI_Codigo_ISO="GT"); db.add(pais); await db.flush()
        estado = Estado(EST_Nombre="Guatemala", PAI_Pais=pais.PAI_Pais); db.add(estado); await db.flush()
        muni = Municipio(MUN_Nombre="Ciudad de Guatemala", EST_Estado=estado.EST_Estado); db.add(muni); await db.flush()
        sede = Sede(SED_Nombre="Torre Futura", MUN_Municipio=muni.MUN_Municipio); db.add(sede); await db.flush()
        edificio = Edificio(EDI_Nombre="Torre Norte", SED_Sede=sede.SED_Sede); db.add(edificio); await db.flush()
        nivel = Nivel(NIV_Numero_Piso="Piso 12", EDI_Edificio=edificio.EDI_Edificio); db.add(nivel); await db.flush()
        area = Area(ARE_Nombre="Datacenter Principal", ARE_Tipo_Acceso="Biométrico", NIV_Nivel=nivel.NIV_Nivel); db.add(area); await db.flush()

        # -------------------------------------------------------
        # 4. CATÁLOGOS TÉCNICOS
        # -------------------------------------------------------
        logger.info("🔹 3. Estandarizando Catálogos...")
        tipo_activo = TipoActivo(TAC_Nombre="Laptop")
        marca = Marca(MAR_Nombre="Dell")
        conexion = TipoConexion(TCN_Nombre="WiFi 6 / BT 5.0")
        estado_op = EstadoOperativo(EOP_Nombre="Asignado") # Estado inicial
        tipo_spec = TipoEspecificacion(TES_Nombre="Memoria RAM", TES_Unidad_Medida="GB")
        
        db.add_all([tipo_activo, marca, conexion, estado_op, tipo_spec]); await db.flush()

        modelo = Modelo(MOD_Nombre="Latitude 7440", MAR_Marca=marca.MAR_Marca, TCN_Tipo_Conexion=conexion.TCN_Tipo_Conexion)
        db.add(modelo); await db.flush()

        # -------------------------------------------------------
        # 5. CORE (Activo Maestro)
        # -------------------------------------------------------
        logger.info("🔹 4. Registrando Activo Maestro (LPT-001)...")
        activo = Activo(
            ACT_Codigo_Interno="LPT-001",
            ACT_Serie_Fabricante="SERVICE-TAG-X1",
            ACT_Hostname="LPT-JUAN-V1", # Hostname inicial
            ACT_Fecha_Compra=date(2024, 1, 1),
            ACT_Costo=1850.50,
            MOD_Modelo=modelo.MOD_Modelo,
            TAC_Tipo_Activo=tipo_activo.TAC_Tipo_Activo,
            EOP_Estado_Operativo=estado_op.EOP_Estado_Operativo
        )
        db.add(activo); await db.flush()

        # Spec: 32GB RAM
        spec = Especificacion(
            ACT_Activo=activo.ACT_Activo,
            TES_Tipo_Especificacion=tipo_spec.TES_Tipo_Especificacion,
            ESP_Valor="32"
        )
        db.add(spec)

        # -------------------------------------------------------
        # 6. TRAZABILIDAD ACTIVO (Preparamos el escenario)
        # -------------------------------------------------------
        logger.info("🔹 5. Asignando Activo a JUAN (Escenario Inicial)...")
        
        tipo_mov_asig = TipoMovimiento(TMO_Nombre="Asignación")
        tipo_mov_pres = TipoMovimiento(TMO_Nombre="Préstamo")
        db.add_all([tipo_mov_asig, tipo_mov_pres]); await db.flush()

        # Creamos la asignación VIGENTE para Juan.
        # Cuando tú uses la API para asignar a Pedro, esta fila debe cerrarse sola.
        movimiento_juan = Movimiento(
            ACT_Activo=activo.ACT_Activo,
            PER_Persona=persona_juan.PER_Persona,
            ARE_Area=area.ARE_Area,
            TMO_Tipo_Movimiento=tipo_mov_asig.TMO_Tipo_Movimiento,
            MOV_Observacion="Entrega inicial de equipo nuevo",
            MOV_Fecha_Asignacion=datetime.now()
            # MOV_Fecha_Devolucion se deja NULL (Vigente)
        )
        db.add(movimiento_juan)

        # -------------------------------------------------------
        # 7. TRAZABILIDAD SOFTWARE (Prueba de Historia)
        # -------------------------------------------------------
        logger.info("🔹 6. Generando Historial de Software...")
        
        # A. Catálogos Software
        tipo_lic = TipoLicencia(TLI_Nombre="SaaS (Suscripción)")
        sw_office = Software(SOF_Nombre="Office 365 E3", SOF_Fabricante="Microsoft")
        db.add_all([tipo_lic, sw_office]); await db.flush()

        # B. Licencia (Inventario Digital)
        licencia = Licencia(
            SOF_Software=sw_office.SOF_Software,
            TLI_Tipo_Licencia=tipo_lic.TLI_Tipo_Licencia,
            LIC_Clave_Activacion="TENANT-ID-XYZ",
            LIC_Cantidad_Total=2,
            LIC_Cantidad_Usada=1 
        )
        db.add(licencia); await db.flush()

        # C. HISTORIA PASADA: Se instaló hace un mes y se desinstaló ayer
        inst_historia = Instalacion(
            ACT_Activo=activo.ACT_Activo,
            LIC_Licencia=licencia.LIC_Licencia,
            INS_Fecha_Instalacion=date(2024, 2, 1),
            INS_Estado=False # <--- YA NO ESTÁ INSTALADO (HISTÓRICO)
        )
        db.add(inst_historia)

        # D. ESTADO ACTUAL: Se volvió a instalar hoy
        inst_actual = Instalacion(
            ACT_Activo=activo.ACT_Activo,
            LIC_Licencia=licencia.LIC_Licencia,
            INS_Fecha_Instalacion=date.today(),
            INS_Estado=True # <--- ESTÁ INSTALADO ACTUALMENTE
        )
        db.add(inst_actual)
        
        # Ajustamos contador de uso (1 ocupada)
        licencia.LIC_Cantidad_Usada = 1
        db.add(licencia)

        # -------------------------------------------------------
        # CIERRE
        # -------------------------------------------------------
        await db.commit()
        logger.info("✅ ¡SIEMBRA COMPLETADA! EL SISTEMA ESTÁ LISTO.")
        logger.info("------------------------------------------------")
        logger.info(f" Activo UUID: {activo.ACT_Activo}")
        logger.info(f" Persona Juan UUID (Dueño Actual): {persona_juan.PER_Persona}")
        logger.info(f" Persona Pedro UUID (Nuevo Dueño): {persona_pedro.PER_Persona}")
        logger.info("------------------------------------------------")

if __name__ == "__main__":
    asyncio.run(seed_data())