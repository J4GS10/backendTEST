import asyncio
import logging
from datetime import date, datetime
from app.db.session import SessionLocal
from app.core.security import get_password_hash

# 1. IMPORTACIÓN TOTAL DE MODELOS
from app.models.organization import Departamento, Cargo, Persona, Usuario
from app.models.location import Pais, Estado, Municipio, Sede, Edificio, Nivel, Area
from app.models.catalogs import TipoActivo, Marca, TipoConexion, Modelo, EstadoOperativo, TipoEspecificacion
from app.models.core import Activo, Especificacion
from app.models.traceability import TipoMovimiento, Movimiento, TipoMantenimiento, TipoEvidencia, Mantenimiento
from app.models.software import TipoLicencia, Software, Licencia, Instalacion
from app.models.governance import ConfiguracionSistema, Secuencia

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def seed_data():
    async with SessionLocal() as db:
        logger.info(" INICIANDO SIEMBRA MAESTRA (V FINAL)...")

        # --- 1. GOBIERNO ---
        config = ConfiguracionSistema(SYS_Nombre_Empresa="TechCorp", SYS_Color_Primario="#000", SYS_Idioma_Defecto="es")
        db.add(config)

        # --- 2. ORGANIZACIÓN ---
        logger.info("1. Estructura Org...")
        depto = Departamento(DEP_Nombre="IT", DEP_Codigo_Costos="IT-01"); 
        cargo = Cargo(CAR_Nombre="Admin"); 
        db.add_all([depto, cargo]); await db.flush()

        persona_juan = Persona(PER_Primer_Nombre="Juan", PER_Primer_Apellido="Perez", PER_Email_Corporativo="juan@test.com", DEP_Departamento=depto.DEP_Departamento, CAR_Cargo=cargo.CAR_Cargo)
        persona_pedro = Persona(PER_Primer_Nombre="Pedro", PER_Primer_Apellido="Gomez", PER_Email_Corporativo="pedro@test.com", DEP_Departamento=depto.DEP_Departamento, CAR_Cargo=cargo.CAR_Cargo)
        db.add_all([persona_juan, persona_pedro]); await db.flush()

        usuario = Usuario(USU_Username="admin", USU_Password_Hash=get_password_hash("admin123"), USU_Salt="auto", USU_Rol="SUPER_ADMIN", PER_Persona=persona_juan.PER_Persona)
        db.add(usuario)

        # --- 3. UBICACIÓN ---
        logger.info(" 2. Mapa Geográfico...")
        pais = Pais(PAI_Nombre="GT", PAI_Codigo_ISO="GT"); db.add(pais); await db.flush()
        estado = Estado(EST_Nombre="GT", PAI_Pais=pais.PAI_Pais); db.add(estado); await db.flush()
        muni = Municipio(MUN_Nombre="GT", EST_Estado=estado.EST_Estado); db.add(muni); await db.flush()
        sede = Sede(SED_Nombre="Central", MUN_Municipio=muni.MUN_Municipio); db.add(sede); await db.flush()
        edi = Edificio(EDI_Nombre="T1", SED_Sede=sede.SED_Sede); db.add(edi); await db.flush()
        nivel = Nivel(NIV_Numero_Piso="1", EDI_Edificio=edi.EDI_Edificio); db.add(nivel); await db.flush()
        
        area_bodega = Area(ARE_Nombre="Bodega Central", ARE_Tipo_Acceso="Restringido", NIV_Nivel=nivel.NIV_Nivel)
        area_oficina = Area(ARE_Nombre="Oficina 101", ARE_Tipo_Acceso="General", NIV_Nivel=nivel.NIV_Nivel)
        db.add_all([area_bodega, area_oficina]); await db.flush()

        # --- 4. CATÁLOGOS Y SECUENCIAS ---
        logger.info(" 3. Catálogos y Secuencias...")
        # CRÍTICO: Definir prefijo LPT
        tipo_activo = TipoActivo(TAC_Nombre="Laptop", TAC_Prefijo="NB")
        marca = Marca(MAR_Nombre="Dell"); 
        conexion = TipoConexion(TCN_Nombre="WiFi"); 
        estado_op = EstadoOperativo(EOP_Nombre="STATUS.ASSIGNED"); 
        tipo_spec = TipoEspecificacion(TES_Nombre="RAM", TES_Unidad_Medida="GB")
        db.add_all([tipo_activo, marca, conexion, estado_op, tipo_spec]); await db.flush()

        modelo = Modelo(MOD_Nombre="XPS 13", MAR_Marca=marca.MAR_Marca, TCN_Tipo_Conexion=conexion.TCN_Tipo_Conexion)
        db.add(modelo); await db.flush()

        # CRÍTICO: Inicializar secuencia en 1 (porque crearemos LPT00001 manual abajo)
        secuencia = Secuencia(SEC_Contexto="ASSET_NB", SEC_Ultimo_Numero=1, SEC_Relleno=5)
        db.add(secuencia); await db.flush()

        # --- 5. TRAZABILIDAD (Tipos) ---
        logger.info(" 4. Tipos de Movimiento...")
        # CRÍTICO: Nombres exactos para la búsqueda automática
        tipo_ingreso = TipoMovimiento(TMO_Nombre="Ingreso Inicial") 
        tipo_asignacion = TipoMovimiento(TMO_Nombre="Asignación de Equipo")
        # Tipos para mantenimiento y evidencia
        tipo_mant = TipoMantenimiento(TMA_Nombre="Correctivo")
        tipo_evi = TipoEvidencia(TEV_Nombre="Acta")
        db.add_all([tipo_ingreso, tipo_asignacion, tipo_mant, tipo_evi]); await db.flush()

        # --- 6. CORE (Activo Maestro) ---
        logger.info(" 5. Registrando Activo Maestro...")
        activo = Activo(
            ACT_Codigo_Interno="NB00001", # Coincide con la secuencia manual
            ACT_Serie_Fabricante="SN-999",
            ACT_Hostname="HOST-01",
            ACT_Fecha_Compra=date(2025,1,1),
            MOD_Modelo=modelo.MOD_Modelo,
            TAC_Tipo_Activo=tipo_activo.TAC_Tipo_Activo,
            EOP_Estado_Operativo=estado_op.EOP_Estado_Operativo
        )
        db.add(activo); await db.flush()

        # --- 7. HISTORIA COMPLETA ---
        logger.info("6. Generando Historia...")
        
        # A. Ingreso (Histórico cerrado)
        mov_1 = Movimiento(
            ACT_Activo=activo.ACT_Activo,
            PER_Persona=persona_juan.PER_Persona, 
            ARE_Area=area_bodega.ARE_Area,
            TMO_Tipo_Movimiento=tipo_ingreso.TMO_Tipo_Movimiento,
            MOV_Observacion="Compra inicial",
            MOV_Fecha_Asignacion=datetime(2025,1,1, 8,0,0),
            MOV_Fecha_Devolucion=datetime(2025,1,2, 9,0,0) 
        )
        
        # B. Asignación Vigente a Juan
        mov_2 = Movimiento(
            ACT_Activo=activo.ACT_Activo,
            PER_Persona=persona_juan.PER_Persona, 
            ARE_Area=area_oficina.ARE_Area,
            TMO_Tipo_Movimiento=tipo_asignacion.TMO_Tipo_Movimiento,
            MOV_Observacion="Entrega a usuario final",
            MOV_Fecha_Asignacion=datetime(2025,1,2, 9,0,0),
            MOV_Fecha_Devolucion=None # VIGENTE
        )
        db.add_all([mov_1, mov_2])

        # --- 8. SOFTWARE ---
        logger.info("🔹 7. Software...")
        tipo_lic = TipoLicencia(TLI_Nombre="SaaS")
        sw = Software(SOF_Nombre="Office", SOF_Fabricante="MS")
        db.add_all([tipo_lic, sw]); await db.flush()

        licencia = Licencia(
            SOF_Software=sw.SOF_Software, TLI_Tipo_Licencia=tipo_lic.TLI_Tipo_Licencia,
            LIC_Cantidad_Total=2, LIC_Cantidad_Usada=1
        )
        db.add(licencia); await db.flush()

        # Instalación activa
        inst = Instalacion(ACT_Activo=activo.ACT_Activo, LIC_Licencia=licencia.LIC_Licencia, INS_Fecha_Instalacion=date.today(), INS_Estado=True)
        db.add(inst)

        await db.commit()
        logger.info(f" ¡LISTO! Activo UUID: {activo.ACT_Activo}")
        logger.info(f" Persona PEDRO UUID: {persona_pedro.PER_Persona}")

if __name__ == "__main__":
    asyncio.run(seed_data())