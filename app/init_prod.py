import asyncio
import logging
from app.db.session import SessionLocal
from app.core.security import get_password_hash
from app.models.organization import Departamento, Cargo, Persona, Usuario
from app.models.governance import ConfiguracionSistema

# Configuración
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_production():
    async with SessionLocal() as db:
        logger.info("🏭 INICIALIZANDO ENTORNO DE PRODUCCIÓN...")

        # 1. Configuración Base (Marca Blanca Default)
        config = ConfiguracionSistema(
            SYS_Nombre_Empresa="Mi Empresa TI",
            SYS_Color_Primario="#19d222", # Azul Genérico
            SYS_Idioma_Defecto="es"
        )
        db.add(config)

        # 2. Estructura Admin Mínima
        depto_sys = Departamento(DEP_Nombre="SysAdmin", DEP_Codigo_Costos="SYS-000", DEP_Descripcion="Cuenta Raíz")
        cargo_sys = Cargo(CAR_Nombre="SysAdmin", CAR_Es_Jefatura=True)
        db.add_all([depto_sys, cargo_sys]); await db.flush()

        # 3. El Primer Super Usuario
        persona_admin = Persona(
            PER_Primer_Nombre="SysAdmin", 
            PER_Primer_Apellido="Inventario", 
            PER_Email_Corporativo="info.gt@lombardi.group",
            DEP_Departamento=depto_sys.DEP_Departamento, 
            CAR_Cargo=cargo_sys.CAR_Cargo
        )
        db.add(persona_admin); await db.flush()


        await db.commit()
        logger.info('')
        # Credenciales Iniciales
        usuario_admin = Usuario(
            USU_Username="sa",
            USU_Password_Hash=get_password_hash("ChangeMe123!"), 
            USU_Salt="auto",
            USU_Rol="SUPER_ADMIN",
            PER_Persona=persona_admin.PER_Persona,
            USU_Estado=True
        )
        db.add(usuario_admin)

        await db.commit()
        logger.info(" SISTEMA INICIALIZADO.")
        logger.info(" Credenciales: sa / ChangeMe123!")
        logger.info(" POR FAVOR CAMBIE ESTA CONTRASEÑA INMEDIATAMENTE.")

if __name__ == "__main__":
    asyncio.run(init_production())