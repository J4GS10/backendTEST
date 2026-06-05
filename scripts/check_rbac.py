#!/usr/bin/env python3
"""
Guard de RBAC: falla (exit 1) si algún endpoint MUTADOR (POST/PUT/PATCH/DELETE)
carece de un guard de rol (`require_admin` / `require_super_admin` /
`require_operativo`, o las constantes WRITE/ADMIN/SUPER/OPERATIVO).

Se excluyen los routers de autoservicio (`login.py`, `twofactor.py`), donde la
identidad del propio usuario en el JWT es el control de acceso, y el endpoint de
búsqueda `POST /core/activos/search`, que es de lectura aunque use POST.

Uso:
    python scripts/check_rbac.py
Pensado para correr en CI junto a ruff/pytest.
"""
from __future__ import annotations

import re
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "endpoints"
MUTATOR = re.compile(r"@router\.(post|put|patch|delete)\(")
ROLE_TOKENS = (
    "require_admin", "require_super_admin", "require_operativo",
    "WRITE", "ADMIN", "SUPER", "OPERATIVO",
)
SELF_SERVICE_FILES = {"login.py", "twofactor.py"}
# Lecturas implementadas como POST (llevan cuerpo de filtros) — no son escritura.
READ_VIA_POST = {("core.py", "/activos/search")}


def scan() -> list[tuple[str, str, str]]:
    gaps: list[tuple[str, str, str]] = []
    for f in sorted(ROOT.glob("*.py")):
        if f.name in SELF_SERVICE_FILES:
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        i = 0
        while i < len(lines):
            m = MUTATOR.search(lines[i])
            if m:
                block = lines[i]
                j = i
                while not block.rstrip().endswith(")") and j < len(lines) - 1:
                    j += 1
                    block += " " + lines[j].strip()
                sig = "".join(lines[j + 1: j + 8])  # firma de la función
                has_role = any(t in block for t in ROLE_TOKENS) or any(
                    t in sig for t in ROLE_TOKENS
                )
                pm = re.search(r'@router\.\w+\(\s*["\']([^"\']*)["\']', block)
                path = pm.group(1) if pm else "?"
                if not has_role and (f.name, path) not in READ_VIA_POST:
                    gaps.append((f.name, m.group(1).upper(), path))
                i = j
            i += 1
    return gaps


def main() -> int:
    gaps = scan()
    if gaps:
        print("FALLO RBAC: mutadores sin guard de rol:")
        for fname, method, path in gaps:
            print(f"  {fname:18} {method:6} {path}")
        return 1
    print("OK RBAC: 0 mutadores sin guard de rol.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
