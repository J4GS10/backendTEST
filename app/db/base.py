from typing import Any
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """
    Clase Base pura.
    """
    id: Any

#IMPORTANTE:
# Importamos todos los modelos aquí para asegurar que SQLAlchemy
# los registre antes de resolver las relaciones cruzadas.
# Esto soluciona el error "failed to locate name".

# 1. Organización y Ubicación (Independientes)
import app.models.organization  
import app.models.location      

# 2. Catálogos y Core (Interdependientes)
# Al importarlos aquí, el Registry de SQLAlchemy se llena correctamente.
import app.models.catalogs      
import app.models.core         

# 3. Resto de módulos
import app.models.software      
import app.models.traceability  
import app.models.governance    