"""
Contraseñas y raíces más usadas (listas públicas de filtraciones, en inglés y
español). Se comparan en minúsculas y también sin los dígitos o símbolos que
suelen agregarse al inicio o al final ("Verano2026!" → "verano").

Es una lista local, sin llamadas a servicios externos: el sistema puede operar
en redes sin salida a Internet.
"""
from __future__ import annotations

COMMON_PASSWORDS: frozenset[str] = frozenset({
    # Numéricas y de teclado
    "123456", "1234567", "12345678", "123456789", "1234567890", "12345", "123123",
    "111111", "000000", "121212", "654321", "666666", "696969", "112233", "159753",
    "147258369", "987654321", "qwerty", "qwertyuiop", "qwerty123", "asdfgh", "asdfghjkl",
    "zxcvbnm", "1q2w3e4r", "1q2w3e", "qazwsx", "1qaz2wsx", "q1w2e3r4", "zaq12wsx",
    "abc123", "abcd1234", "a1b2c3", "aaaaaa", "abcdef", "abcdefg",
    # Inglés
    "password", "passw0rd", "p@ssw0rd", "p@ssword", "letmein", "welcome", "admin",
    "administrator", "root", "login", "master", "secret", "access", "shadow", "superman",
    "batman", "dragon", "monkey", "football", "baseball", "soccer", "hockey", "princess",
    "sunshine", "iloveyou", "trustno1", "starwars", "whatever", "freedom", "michael",
    "jennifer", "jordan", "hunter", "ranger", "summer", "winter", "spring", "autumn",
    "flower", "hello", "charlie", "computer", "internet", "server", "default", "changeme",
    "guest", "user", "test", "testing", "company", "office", "business", "security",
    # Español
    "contrasena", "contraseña", "clave", "micontrasena", "bienvenido", "bienvenida",
    "hola", "holamundo", "teamo", "tequiero", "amor", "amorcito", "corazon", "mimamá",
    "mama", "papa", "familia", "futbol", "barcelona", "realmadrid", "america", "chivas",
    "guatemala", "mexico", "colombia", "peru", "argentina", "chile", "espana",
    "verano", "invierno", "primavera", "otono", "enero", "febrero", "marzo", "abril",
    "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo",
    "cambiame", "temporal", "usuario", "sistema", "empresa", "oficina", "soporte",
    "tecnico", "informatica", "inventario", "seguridad", "acceso", "entrar",
    # Italiano
    "benvenuto", "ciao", "amore", "ciaociao", "juventus", "italia", "estate", "inverno",
})


# Secuencias que no aportan entropía aunque se combinen con otros caracteres.
KEYBOARD_SEQUENCES: tuple[str, ...] = (
    "0123456789", "9876543210", "abcdefghijklmnopqrstuvwxyz", "zyxwvutsrqponmlkjihgfedcba",
    "qwertyuiop", "asdfghjkl", "zxcvbnm", "poiuytrewq", "lkjhgfdsa", "mnbvcxz",
)
