import sys
import os

# Asegurar que el directorio raíz está en PYTHONPATH
sys.path.append("/app")

print("--- INICIANDO DIAGNÓSTICO DE ARRANQUE ---")
try:
    print("1. Importando app.main...")
    from app.main import app
    print("✅ app.main importado ÉXITOSAMENTE")
except ImportError as e:
    print(f"❌ ImportError: {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"❌ Exception General: {e}")
    import traceback
    traceback.print_exc()
print("--- FIN DIAGNÓSTICO ---")
