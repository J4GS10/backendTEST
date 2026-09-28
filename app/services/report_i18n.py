"""
Traducción de valores canónicos para documentos y reportes generados
(actas Word/PDF, exportaciones CSV y etiquetas QR).

Los catálogos del sistema (estados operativos, tipos de movimiento, tipos de
activo, estados de orden de compra, acciones de auditoría, unidades) se
almacenan en español o como códigos. Al generar un documento en inglés o
italiano, esos valores se traducen aquí. Los valores no reconocidos (datos
libres creados por el usuario) se devuelven sin cambios.
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

SUPPORTED_LANGS = ("es", "en", "it")
DEFAULT_LANG = "es"


def normalize_lang(lang: str | None) -> str:
    value = (lang or DEFAULT_LANG).split("-")[0].split("_")[0].strip().lower()
    return value if value in SUPPORTED_LANGS else DEFAULT_LANG


def _key(value: str) -> str:
    """Clave de búsqueda: sin acentos, minúsculas, espacios/guiones normalizados."""
    s = unicodedata.normalize("NFKD", str(value))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.replace("_", " ").replace(".", " ").casefold().split())


# ---------------------------------------------------------------------------
# Catálogos canónicos: {clave: {"es": ..., "en": ..., "it": ...}}
# Cada entrada puede tener alias (códigos o variantes) que apuntan a ella.
# ---------------------------------------------------------------------------
def _entry(es: str, en: str, it: str, *aliases: str) -> tuple[tuple[str, ...], dict[str, str]]:
    return ((es, *aliases), {"es": es, "en": en, "it": it})


_ESTADOS_OPERATIVOS = [
    _entry("Disponible", "Available", "Disponibile", "STATUS.AVAILABLE", "AVAILABLE"),
    _entry("Asignado", "Assigned", "Assegnato", "STATUS.ASSIGNED", "ASSIGNED"),
    _entry("En Bodega", "In Storage", "In magazzino", "Bodega", "STATUS.IN_STORAGE", "IN_STORAGE"),
    _entry("En Reparación", "Under Repair", "In riparazione", "Reparación",
           "STATUS.IN_REPAIR", "IN_REPAIR", "En Mantenimiento"),
    _entry("Baja", "Decommissioned", "Dismesso", "De Baja", "STATUS.RETIRED", "RETIRED"),
    _entry("En Tránsito", "In Transit", "In transito", "STATUS.IN_TRANSIT", "IN_TRANSIT"),
    _entry("Prestado", "On Loan", "In prestito", "En Préstamo", "STATUS.ON_LOAN"),
    _entry("Extraviado", "Lost", "Smarrito", "Perdido", "STATUS.LOST"),
]

_TIPOS_MOVIMIENTO = [
    _entry("Ingreso", "Intake", "Presa in carico", "Ingreso Inicial"),
    _entry("Asignación", "Assignment", "Assegnazione", "Asignación de Equipo", "ASSIGN"),
    _entry("Devolución", "Return", "Restituzione", "RETURN"),
    _entry("Transferencia", "Transfer", "Trasferimento", "TRANSFER"),
    _entry("Préstamo", "Loan", "Prestito", "LOAN"),
    _entry("Baja por Retiro", "Retirement", "Dismissione", "Retiro"),
]

_TIPOS_ACTIVO = [
    _entry("Laptop", "Laptop", "Laptop", "Portátil", "Notebook"),
    _entry("Desktop", "Desktop", "Desktop", "Computadora de escritorio", "PC de escritorio"),
    _entry("Monitor", "Monitor", "Monitor"),
    _entry("Teclado", "Keyboard", "Tastiera"),
    _entry("Mouse", "Mouse", "Mouse", "Ratón"),
    _entry("Teclado/Mouse", "Keyboard/Mouse", "Tastiera/Mouse", "Teclado y Mouse", "Teclado / Mouse"),
    _entry("Servidor", "Server", "Server"),
    _entry("Impresora", "Printer", "Stampante"),
    _entry("Tablet", "Tablet", "Tablet", "Tableta"),
    _entry("Teléfono", "Phone", "Telefono", "Telefono"),
    _entry("Celular", "Mobile phone", "Cellulare", "Teléfono celular", "Smartphone"),
    _entry("Escáner", "Scanner", "Scanner", "Scanner"),
    _entry("Proyector", "Projector", "Proiettore"),
    _entry("Router", "Router", "Router"),
    _entry("Switch", "Switch", "Switch"),
    _entry("Access Point", "Access point", "Access point", "Punto de acceso"),
    _entry("Diadema", "Headset", "Cuffie", "Audífonos", "Headset"),
    _entry("Cámara", "Camera", "Videocamera", "Camara web", "Webcam"),
    _entry("Docking Station", "Docking station", "Docking station", "Base de acoplamiento"),
    _entry("UPS", "UPS", "Gruppo di continuità", "No break"),
    _entry("Cargador", "Charger", "Caricabatterie"),
]

_ESTADOS_ORDEN = [
    _entry("Borrador", "Draft", "Bozza", "BORRADOR"),
    _entry("Recibida", "Received", "Ricevuto", "RECIBIDA"),
    _entry("Cancelada", "Cancelled", "Annullato", "CANCELADA"),
]

_ACCIONES_AUDITORIA = [
    _entry("Creación", "Creation", "Creazione", "CREATE"),
    _entry("Actualización", "Update", "Aggiornamento", "UPDATE"),
    _entry("Eliminación", "Deletion", "Eliminazione", "DELETE"),
    _entry("Eliminación lógica", "Soft deletion", "Eliminazione logica", "DELETE_LOGIC"),
    _entry("Inicio de sesión exitoso", "Successful sign-in", "Accesso riuscito", "LOGIN_SUCCESS"),
    _entry("Inicio de sesión fallido", "Failed sign-in", "Accesso non riuscito", "LOGIN_FAILED"),
    _entry("Cierre de sesión", "Sign-out", "Disconnessione", "LOGOUT"),
    _entry("Cierre de todas las sesiones", "Sign-out from all sessions",
           "Disconnessione da tutte le sessioni", "LOGOUT_ALL"),
    _entry("Desvinculación de colaborador", "Employee offboarding",
           "Cessazione del collaboratore", "OFFBOARDING"),
    _entry("Cambio de contraseña", "Password change", "Modifica della password", "PASSWORD_CHANGE"),
    _entry("Restablecimiento de contraseña", "Password reset",
           "Reimpostazione della password", "PASSWORD_RESET"),
    _entry("Solicitud de restablecimiento de contraseña", "Password reset request",
           "Richiesta di reimpostazione della password", "PASSWORD_RESET_REQUEST"),
    _entry("Reutilización de token de renovación", "Refresh token reuse",
           "Riutilizzo del token di rinnovo", "REFRESH_TOKEN_REUSE"),
    _entry("Asignación", "Assignment", "Assegnazione", "ASSIGN"),
    _entry("Devolución", "Return", "Restituzione", "RETURN"),
    _entry("Transferencia", "Transfer", "Trasferimento", "TRANSFER"),
    _entry("Instalación", "Installation", "Installazione", "INSTALL"),
    _entry("Desinstalación", "Uninstallation", "Disinstallazione", "UNINSTALL"),
    _entry("Entrada de inventario", "Stock receipt", "Carico di magazzino", "STOCK_IN"),
    _entry("Salida de inventario", "Stock issue", "Scarico di magazzino", "STOCK_OUT"),
    _entry("Cierre", "Closure", "Chiusura", "CLOSE"),
    _entry("Importación de datos (simulación)", "Data import (dry run)",
           "Importazione dati (simulazione)", "DATASET_IMPORT_DRY_RUN"),
]

_UNIDADES = [
    _entry("unidad", "unit", "unità", "unidades", "und", "u"),
    _entry("caja", "box", "scatola", "cajas"),
    _entry("paquete", "pack", "confezione", "paquetes"),
    _entry("rollo", "roll", "rotolo", "rollos"),
    _entry("resma", "ream", "risma", "resmas"),
    _entry("litro", "liter", "litro", "litros"),
    _entry("metro", "meter", "metro", "metros"),
    _entry("par", "pair", "paio", "pares"),
    _entry("juego", "set", "set", "juegos", "kit"),
]


def _build(entries) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for aliases, translations in entries:
        for alias in (*aliases, translations["en"], translations["it"]):
            index.setdefault(_key(alias), translations)
    return index


_CATALOGS: dict[str, dict[str, dict[str, str]]] = {
    "estado_operativo": _build(_ESTADOS_OPERATIVOS),
    "tipo_movimiento": _build(_TIPOS_MOVIMIENTO),
    "tipo_activo": _build(_TIPOS_ACTIVO),
    "estado_orden": _build(_ESTADOS_ORDEN),
    "accion_auditoria": _build(_ACCIONES_AUDITORIA),
    "unidad": _build(_UNIDADES),
}


def translate_catalog(catalog: str, value, lang: str | None) -> str:
    """Traduce un valor canónico de catálogo. Si no se reconoce, se devuelve tal cual."""
    if value is None:
        return ""
    raw = str(value)
    if not raw.strip():
        return raw
    entry = _CATALOGS[catalog].get(_key(raw))
    if entry is None:
        return raw
    return entry[normalize_lang(lang)]


# ---------------------------------------------------------------------------
# Booleanos, fechas y montos
# ---------------------------------------------------------------------------
_YES_NO = {"es": ("Sí", "No"), "en": ("Yes", "No"), "it": ("Sì", "No")}


def yes_no(value: bool, lang: str | None) -> str:
    yes, no = _YES_NO[normalize_lang(lang)]
    return yes if value else no


MONTHS = {
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
           "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"],
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
           "agosto", "settembre", "ottobre", "novembre", "dicembre"],
}


def format_long_date(value: date, lang: str | None) -> str:
    """es: 24 de septiembre de 2026 · en: September 24, 2026 · it: 24 settembre 2026."""
    lang = normalize_lang(lang)
    month = MONTHS[lang][value.month - 1]
    if lang == "en":
        return f"{month} {value.day}, {value.year}"
    if lang == "it":
        # En italiano el primer día del mes se escribe como ordinal: "1º".
        day = "1º" if value.day == 1 else str(value.day)
        return f"{day} {month} {value.year}"
    return f"{value.day} de {month} de {value.year}"


def format_iso_date(value) -> str:
    """Fecha en ISO 8601 (AAAA-MM-DD): inequívoca en cualquier configuración regional de Excel."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    try:
        return value.strftime("%Y-%m-%d")
    except (AttributeError, ValueError):
        return str(value)


def format_iso_datetime(value) -> str:
    """Fecha y hora 'AAAA-MM-DD HH:MM:SS' (sin la 'T' ISO ni microsegundos)."""
    if value is None:
        return ""
    try:
        return value.strftime("%Y-%m-%d %H:%M:%S")
    except (AttributeError, ValueError):
        return str(value)


def format_amount(value) -> str:
    """Monto con 2 decimales y punto decimal, sin separador de miles (apto para hojas de cálculo)."""
    if value is None or value == "":
        return ""
    try:
        return f"{Decimal(str(value)).quantize(Decimal('0.01'))}"
    except (InvalidOperation, ValueError):
        return str(value)
