"""
Importa inventarios HTML reales desde la carpeta dataset.

Objetivo:
- Convertir reportes HTML de equipos en activos gestionables.
- Mantener trazabilidad con movimientos abiertos por custodia.
- Guardar informacion tecnica como especificaciones del activo.
- Ser idempotente: se puede ejecutar varias veces sin duplicar activos.

Uso dentro del contenedor backend:
    python -m app.seed_dataset_inventory --dataset /tmp/dataset --dry-run
    python -m app.seed_dataset_inventory --dataset /tmp/dataset
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models.catalogs import EstadoOperativo, Marca, Modelo, TipoActivo, TipoEspecificacion
from app.models.core import Activo, Especificacion
from app.models.governance import AuditoriaSistema
from app.models.location import Area, Edificio, Estado, Municipio, Nivel, Pais, Sede
from app.models.organization import Cargo, Departamento, Persona, Usuario
from app.models.traceability import Movimiento, TipoMovimiento

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("seed_dataset_inventory")

IMPORT_AGENT = "app.seed_dataset_inventory"
IMPORT_ENTITY = "DATASET_INVENTORY"
DEFAULT_EMAIL_DOMAIN = "lombardi.dataset.local"
GENERIC_USERS = {
    "administrator",
    "administrador",
    "admin",
    "lombardilatino",
    "pivote",
    "pivote01",
    "inge.pe",
    "soporte",
    "support",
}


@dataclass(frozen=True)
class InventoryRecord:
    file_name: str
    hostname: str
    username: str
    display_name: str | None
    generated_at: datetime | None
    cards: dict[str, str]
    tables: dict[str, list[dict[str, str]]]

    @property
    def serial(self) -> str:
        return self.cards.get("Numero de serie", "").strip()

    @property
    def brand(self) -> str:
        raw = self.cards.get("Marca", "").strip()
        if _norm(raw) in {"hewlett-packard", "hewlett packard"}:
            return "HP"
        return raw or "Sin marca"

    @property
    def model(self) -> str:
        return self.cards.get("Modelo", "").strip() or "Modelo no informado"

    @property
    def system_os(self) -> str:
        return self.cards.get("Sistema operativo", "").strip()

    @property
    def purchase_reference_date(self) -> date:
        # El modelo exige fecha de compra. El dataset no trae compra real, asi
        # que usamos la fecha del inventario y la dejamos explicita en specs.
        return (self.generated_at.date() if self.generated_at else date.today())


def _clean(fragment: str) -> str:
    fragment = re.sub(r"<[^>]+>", " ", fragment, flags=re.S)
    fragment = html.unescape(fragment)
    fragment = fragment.replace("\xa0", " ")
    return re.sub(r"\s+", " ", fragment).strip()


def _norm(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold().strip()


def _slug(value: str) -> str:
    text = _norm(value)
    text = re.sub(r"[^a-z0-9.]+", ".", text)
    text = re.sub(r"\.+", ".", text).strip(".")
    return text[:50] or "sin.usuario"


def _clip(value: Any, max_len: int = 255) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_len:
        return text
    marker = "..."
    return text[: max_len - len(marker)].rstrip() + marker


def _parse_table(table_html: str) -> list[dict[str, str]]:
    headers = [_clean(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", table_html, flags=re.S | re.I)]
    rows: list[dict[str, str]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.S | re.I):
        cells = [_clean(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)]
        if not cells:
            continue
        if headers and len(headers) == len(cells):
            rows.append(dict(zip(headers, cells)))
        else:
            rows.append({f"col_{idx + 1}": cell for idx, cell in enumerate(cells)})
    return rows


def _extract_display_name(file_name: str, hostname: str, username: str) -> str | None:
    stem = Path(file_name).stem
    tail = stem
    if stem.upper().startswith(hostname.upper()):
        tail = stem[len(hostname):].lstrip(" -_")

    tail = re.sub(
        r"(?i)^windows\s*10\s*pro[-_ ]*(?:\d{2}h\d)?[-_ ]*",
        "",
        tail,
    ).strip(" -_")
    tail = re.sub(
        r"(?i)^windows10pro[-_ ]*(?:\d{2}h\d)?[-_ ]*",
        "",
        tail,
    ).strip(" -_")

    if not tail or _norm(tail) in GENERIC_USERS or re.fullmatch(r"(?i)pivote\d*", tail):
        return None

    cleaned = re.sub(r"[-_]+", " ", tail).strip()
    if len(cleaned) < 3 or _norm(cleaned) == _norm(username):
        return None
    return " ".join(part.capitalize() for part in cleaned.split())


def _parse_generated_at(text: str) -> datetime | None:
    match = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})", text)
    if not match:
        return None
    try:
        return datetime.strptime(" ".join(match.groups()), "%d/%m/%Y %H:%M")
    except ValueError:
        return None


def parse_inventory_file(path: Path) -> InventoryRecord:
    text = path.read_text(encoding="utf-8", errors="replace")
    cards = {
        _clean(key): _clean(value)
        for key, value in re.findall(
            r"<div class=['\"]k['\"]>(.*?)</div>\s*<div class=['\"]v['\"]>(.*?)</div>",
            text,
            flags=re.S | re.I,
        )
    }
    hostname = cards.get("Hostname", "").strip()
    username = cards.get("Usuario", "").strip()
    tables: dict[str, list[dict[str, str]]] = {}
    for section_title, section_body in re.findall(
        r"<section[^>]*>\s*<h2>(.*?)</h2>(.*?)</section>",
        text,
        flags=re.S | re.I,
    ):
        title = _clean(section_title)
        section_rows: list[dict[str, str]] = []
        for table in re.findall(r"<table[^>]*>(.*?)</table>", section_body, flags=re.S | re.I):
            section_rows.extend(_parse_table(table))
        tables[title] = section_rows

    return InventoryRecord(
        file_name=path.name,
        hostname=hostname,
        username=username,
        display_name=_extract_display_name(path.name, hostname, username),
        generated_at=_parse_generated_at(text),
        cards=cards,
        tables=tables,
    )


def load_dataset(dataset_dir: Path) -> list[InventoryRecord]:
    files = sorted(dataset_dir.glob("*.html"))
    if not files:
        raise RuntimeError(f"No HTML files found in dataset directory: {dataset_dir}")

    records = [parse_inventory_file(path) for path in files]
    missing = [
        record.file_name
        for record in records
        if not record.hostname or not record.username or not record.serial
    ]
    if missing:
        raise RuntimeError(f"Dataset files with missing hostname/user/serial: {missing}")
    return records


def _asset_type_for(hostname: str) -> tuple[str, str | None]:
    upper = hostname.upper()
    if upper.startswith("NBPE"):
        return ("Laptop", "NB")
    if upper.startswith("PCPE"):
        return ("Desktop", "PC")
    if upper.startswith("WKSPE") or upper.startswith("WKSP"):
        return ("Workstation", "WKS")
    return ("Equipo TI", None)


def _split_person_name(record: InventoryRecord, fallback_name: str) -> tuple[str, str]:
    def safe_part(value: str, fallback: str) -> str:
        cleaned = (value or "").strip()
        if len(cleaned) < 2:
            return fallback
        return _clip(cleaned, 50)

    source = record.display_name or fallback_name
    parts = [p for p in re.split(r"\s+", source.strip()) if p]
    if len(parts) >= 2:
        return (safe_part(parts[0], "Usuario"), safe_part(parts[-1], "Inventariado"))
    if "." in record.username:
        user_parts = [p for p in record.username.split(".") if p]
        if len(user_parts) >= 2:
            return (
                safe_part(user_parts[0].capitalize(), "Usuario"),
                safe_part(user_parts[-1].capitalize(), "Inventariado"),
            )
    return (safe_part(parts[0] if parts else "Usuario", "Usuario"), "Inventariado")


def _is_generic_user(record: InventoryRecord) -> bool:
    user = _norm(record.username)
    display = _norm(record.display_name or "")
    return user in GENERIC_USERS or display in GENERIC_USERS or user.startswith("pivote")


def _primary_mac(rows: list[dict[str, str]]) -> str | None:
    virtual_markers = ("virtual", "fortinet", "vpn", "bluetooth")
    for row in rows:
        desc = _norm(row.get("Descripcion", "") + " " + row.get("Adaptador", ""))
        mac = row.get("MAC")
        if mac and not any(marker in desc for marker in virtual_markers):
            return mac
    for row in rows:
        if row.get("MAC"):
            return row["MAC"]
    return None


def _disk_total_gb(rows: list[dict[str, str]]) -> str:
    total = Decimal("0")
    found = False
    for row in rows:
        size = row.get("Tamano", "")
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(TB|GB)", size, re.I)
        if not match:
            continue
        value = Decimal(match.group(1))
        if match.group(2).upper() == "TB":
            value *= Decimal("1024")
        total += value
        found = True
    return str(total.quantize(Decimal("0.01"))) if found else ""


def _summary(rows: list[dict[str, str]], fields: list[str], limit: int = 255) -> str:
    parts: list[str] = []
    for row in rows:
        values = [row.get(field, "").strip() for field in fields if row.get(field)]
        if values:
            parts.append(" / ".join(values))
    return _clip("; ".join(parts), limit)


def _build_specs(record: InventoryRecord) -> dict[str, str]:
    disks = record.tables.get("Discos", [])
    volumes = record.tables.get("Volumenes / Particiones", [])
    video = record.tables.get("Tarjeta(s) de video", [])
    network = record.tables.get("Adaptadores de red (MAC)", [])
    agents = record.tables.get("Agentes de seguridad y gestion", [])
    win11 = record.tables.get("Aptitud para Windows 11", [])
    memory = record.tables.get("Capacidad y bus de memoria", [])
    profiles = record.tables.get("Perfiles de usuario", [])

    ram = record.cards.get("RAM total", "").replace("GB", "").strip()
    specs = {
        "RAM": ram,
        "Almacenamiento": _disk_total_gb(disks),
        "Procesador": record.cards.get("Procesador", ""),
        "Sistema Operativo": record.system_os,
        "Tarjeta Grafica": _summary(video, ["Tarjeta", "Memoria", "Resolucion", "Driver"]),
        "Version SO": record.cards.get("Version", ""),
        "Build SO": record.cards.get("Build", ""),
        "Arquitectura": record.cards.get("Arquitectura", ""),
        "Generacion CPU": record.cards.get("Generacion", ""),
        "Nucleos Hilos": record.cards.get("Nucleos / Hilos", ""),
        "TPM": record.cards.get("TPM", ""),
        "Aptitud Windows 11": record.cards.get("Apto para Windows 11", ""),
        "Detalle Windows 11": _summary(win11, ["Requisito", "Estado", "Detalle"]),
        "TeamViewer ID": record.cards.get("TeamViewer ID", ""),
        "Agentes seguridad": record.cards.get("Agentes seguridad", ""),
        "Detalle agentes": _summary(agents, ["Producto", "Estado", "Version"]),
        "Memoria detalle": _summary(memory, ["Ranura", "Capacidad", "Tipo (bus)", "Vel. config.", "Fabricante"]),
        "Discos": _summary(disks, ["Disco", "Tipo", "Bus", "Tamano", "Sistema"]),
        "Volumenes": _summary(volumes, ["Unidad", "Sistema arch.", "Total", "Libre", "% Libre"]),
        "MAC principal": _primary_mac(network) or "",
        "Red": _summary(network[:4], ["Adaptador", "Descripcion", "MAC", "Estado"]),
        "Perfiles usuario": _clip(
            f"{len(profiles)} perfiles detectados; usuario de inventario: {record.username}",
        ),
        "Fecha inventario": record.generated_at.isoformat(sep=" ") if record.generated_at else "",
        "Fuente inventario": record.file_name,
        "Usuario detectado": record.username,
    }
    return {name: _clip(value) for name, value in specs.items() if str(value or "").strip()}


async def _one(db: AsyncSession, model, **lookup):
    stmt = select(model)
    for attr, value in lookup.items():
        stmt = stmt.where(getattr(model, attr) == value)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _first_by_norm(db: AsyncSession, model, attr: str, value: str):
    rows = (await db.execute(select(model))).scalars().all()
    wanted = _norm(value)
    return next((row for row in rows if _norm(getattr(row, attr)) == wanted), None)


async def _ensure_state(db: AsyncSession, name: str) -> EstadoOperativo:
    obj = await _first_by_norm(db, EstadoOperativo, "EOP_Nombre", name)
    if obj is None:
        obj = EstadoOperativo(EOP_Nombre=name)
        db.add(obj)
        await db.flush()
    return obj


async def _ensure_movement_type(db: AsyncSession, name: str) -> TipoMovimiento:
    obj = await _first_by_norm(db, TipoMovimiento, "TMO_Nombre", name)
    if obj is None:
        obj = TipoMovimiento(TMO_Nombre=name)
        db.add(obj)
        await db.flush()
    return obj


async def _ensure_type(db: AsyncSession, name: str, prefix: str | None) -> TipoActivo:
    obj = await _first_by_norm(db, TipoActivo, "TAC_Nombre", name)
    if obj is not None:
        if prefix and not obj.TAC_Prefijo:
            prefix_owner = await _one(db, TipoActivo, TAC_Prefijo=prefix)
            if prefix_owner is None:
                obj.TAC_Prefijo = prefix
        return obj
    safe_prefix = None
    if prefix and await _one(db, TipoActivo, TAC_Prefijo=prefix) is None:
        safe_prefix = prefix
    obj = TipoActivo(TAC_Nombre=name, TAC_Prefijo=safe_prefix, TAC_Aplica_Depreciacion=True)
    db.add(obj)
    await db.flush()
    return obj


async def _ensure_brand(db: AsyncSession, name: str) -> Marca:
    obj = await _first_by_norm(db, Marca, "MAR_Nombre", name)
    if obj is None:
        obj = Marca(MAR_Nombre=name)
        db.add(obj)
        await db.flush()
    return obj


async def _ensure_model(db: AsyncSession, record: InventoryRecord, brand: Marca, asset_type: TipoActivo) -> Modelo:
    obj = (await db.execute(
        select(Modelo).where(
            Modelo.MOD_Nombre == record.model,
            Modelo.MAR_Marca == brand.MAR_Marca,
        )
    )).scalar_one_or_none()
    if obj is None:
        obj = Modelo(
            MOD_Nombre=record.model,
            MAR_Marca=brand.MAR_Marca,
            TAC_Tipo_Activo=asset_type.TAC_Tipo_Activo,
        )
        db.add(obj)
        await db.flush()
    elif obj.TAC_Tipo_Activo is None:
        obj.TAC_Tipo_Activo = asset_type.TAC_Tipo_Activo
    return obj


async def _ensure_spec_type(db: AsyncSession, name: str, unit: str | None = None) -> TipoEspecificacion:
    obj = await _first_by_norm(db, TipoEspecificacion, "TES_Nombre", name)
    if obj is None:
        obj = TipoEspecificacion(TES_Nombre=name, TES_Unidad_Medida=unit)
        db.add(obj)
        await db.flush()
    elif unit and not obj.TES_Unidad_Medida:
        obj.TES_Unidad_Medida = unit
    return obj


async def _ensure_location(db: AsyncSession) -> tuple[Area, Area]:
    pais = await _one(db, Pais, PAI_Codigo_ISO="PE")
    if pais is None:
        pais = Pais(PAI_Nombre="Peru", PAI_Codigo_ISO="PE")
        db.add(pais)
        await db.flush()

    estado = await _one(db, Estado, EST_Nombre="Lima", PAI_Pais=pais.PAI_Pais)
    if estado is None:
        estado = Estado(EST_Nombre="Lima", PAI_Pais=pais.PAI_Pais)
        db.add(estado)
        await db.flush()

    municipio = await _one(db, Municipio, MUN_Nombre="Lima", EST_Estado=estado.EST_Estado)
    if municipio is None:
        municipio = Municipio(MUN_Nombre="Lima", EST_Estado=estado.EST_Estado)
        db.add(municipio)
        await db.flush()

    sede = await _one(db, Sede, SED_Nombre="Lombardi Peru", MUN_Municipio=municipio.MUN_Municipio)
    if sede is None:
        sede = Sede(
            SED_Nombre="Lombardi Peru",
            SED_Direccion_Calle="Sede inventariada desde dataset",
            MUN_Municipio=municipio.MUN_Municipio,
        )
        db.add(sede)
        await db.flush()

    edificio = await _one(db, Edificio, EDI_Nombre="Sede Principal", SED_Sede=sede.SED_Sede)
    if edificio is None:
        edificio = Edificio(EDI_Nombre="Sede Principal", SED_Sede=sede.SED_Sede)
        db.add(edificio)
        await db.flush()

    nivel = await _one(db, Nivel, NIV_Numero_Piso="Inventario TI", EDI_Edificio=edificio.EDI_Edificio)
    if nivel is None:
        nivel = Nivel(NIV_Numero_Piso="Inventario TI", NIV_Alias="Dataset 2026", EDI_Edificio=edificio.EDI_Edificio)
        db.add(nivel)
        await db.flush()

    usuarios = await _one(db, Area, ARE_Nombre="Usuarios inventariados", NIV_Nivel=nivel.NIV_Nivel)
    if usuarios is None:
        usuarios = Area(
            ARE_Nombre="Usuarios inventariados",
            ARE_Tipo_Acceso="General",
            ARE_Descripcion="Area logica para custodia importada desde dataset.",
            NIV_Nivel=nivel.NIV_Nivel,
        )
        db.add(usuarios)
        await db.flush()

    staging = await _one(db, Area, ARE_Nombre="TI staging dataset", NIV_Nivel=nivel.NIV_Nivel)
    if staging is None:
        staging = Area(
            ARE_Nombre="TI staging dataset",
            ARE_Tipo_Acceso="Restringido",
            ARE_Descripcion="Custodia temporal para equipos con usuario generico detectado.",
            NIV_Nivel=nivel.NIV_Nivel,
        )
        db.add(staging)
        await db.flush()
    return usuarios, staging


async def _ensure_org(db: AsyncSession) -> tuple[Departamento, Departamento, Cargo, Cargo, Persona]:
    dep_users = await _one(db, Departamento, DEP_Nombre="Usuarios inventariados dataset")
    if dep_users is None:
        dep_users = Departamento(
            DEP_Nombre="Usuarios inventariados dataset",
            DEP_Codigo_Costos="DATASET-2026",
            DEP_Descripcion="Empleados importados desde inventarios HTML.",
        )
        db.add(dep_users)
        await db.flush()

    dep_it = await _one(db, Departamento, DEP_Nombre="TI staging dataset")
    if dep_it is None:
        dep_it = Departamento(
            DEP_Nombre="TI staging dataset",
            DEP_Codigo_Costos="IT-DATASET",
            DEP_Descripcion="Custodia tecnica para equipos sin usuario nominal.",
        )
        db.add(dep_it)
        await db.flush()

    cargo_user = await _one(db, Cargo, CAR_Nombre="Usuario inventariado")
    if cargo_user is None:
        cargo_user = Cargo(CAR_Nombre="Usuario inventariado", CAR_Es_Jefatura=False)
        db.add(cargo_user)
        await db.flush()

    cargo_it = await _one(db, Cargo, CAR_Nombre="Custodia TI dataset")
    if cargo_it is None:
        cargo_it = Cargo(CAR_Nombre="Custodia TI dataset", CAR_Es_Jefatura=False)
        db.add(cargo_it)
        await db.flush()

    staging_person = await _one(db, Persona, PER_Email_Corporativo=f"ti.staging@{DEFAULT_EMAIL_DOMAIN}")
    if staging_person is None:
        staging_person = Persona(
            PER_Primer_Nombre="TI",
            PER_Primer_Apellido="Staging",
            PER_Email_Corporativo=f"ti.staging@{DEFAULT_EMAIL_DOMAIN}",
            DEP_Departamento=dep_it.DEP_Departamento,
            CAR_Cargo=cargo_it.CAR_Cargo,
        )
        db.add(staging_person)
        await db.flush()
    return dep_users, dep_it, cargo_user, cargo_it, staging_person


async def _operator(db: AsyncSession) -> Usuario | None:
    return (await db.execute(
        select(Usuario)
        .where(Usuario.USU_Rol == "SUPER_ADMIN", Usuario.USU_Estado.is_(True))
        .order_by(Usuario.USU_Username)
        .limit(1)
    )).scalar_one_or_none()


async def _ensure_person(
    db: AsyncSession,
    record: InventoryRecord,
    department: Departamento,
    cargo: Cargo,
    staging_person: Persona,
    email_domain: str,
    stats: Counter,
) -> tuple[Persona, bool]:
    if _is_generic_user(record):
        return staging_person, True

    email = f"{_slug(record.username)}@{email_domain}"
    person = await _one(db, Persona, PER_Email_Corporativo=email)
    first, last = _split_person_name(record, record.username)
    if person is None:
        person = Persona(
            PER_Primer_Nombre=first,
            PER_Primer_Apellido=last,
            PER_Email_Corporativo=email,
            DEP_Departamento=department.DEP_Departamento,
            CAR_Cargo=cargo.CAR_Cargo,
        )
        db.add(person)
        await db.flush()
        stats["persons_created"] += 1
    else:
        person.PER_Primer_Nombre = first
        person.PER_Primer_Apellido = last
        person.DEP_Departamento = department.DEP_Departamento
        person.CAR_Cargo = cargo.CAR_Cargo
        person.PER_Estado = True
        stats["persons_updated"] += 1
    return person, False


async def _ensure_asset(
    db: AsyncSession,
    record: InventoryRecord,
    model: Modelo,
    asset_type: TipoActivo,
    state: EstadoOperativo,
    stats: Counter,
) -> Activo:
    code = record.hostname[:50]
    by_serial = await _one(db, Activo, ACT_Serie_Fabricante=record.serial)
    by_code = await _one(db, Activo, ACT_Codigo_Interno=code)
    if by_serial and by_code and by_serial.ACT_Activo != by_code.ACT_Activo:
        raise RuntimeError(
            f"Asset conflict for {record.file_name}: serial {record.serial} and code {code} belong to different assets"
        )

    asset = by_serial or by_code
    if asset is None:
        asset = Activo(
            ACT_Codigo_Interno=code,
            ACT_Serie_Fabricante=record.serial,
            ACT_Hostname=record.hostname,
            ACT_Fecha_Compra=record.purchase_reference_date,
            ACT_Fin_Garantia=None,
            ACT_Costo=None,
            MOD_Modelo=model.MOD_Modelo,
            TAC_Tipo_Activo=asset_type.TAC_Tipo_Activo,
            EOP_Estado_Operativo=state.EOP_Estado_Operativo,
        )
        db.add(asset)
        await db.flush()
        stats["assets_created"] += 1
    else:
        asset.ACT_Hostname = record.hostname
        asset.ACT_Serie_Fabricante = record.serial
        asset.ACT_Fecha_Compra = record.purchase_reference_date
        asset.MOD_Modelo = model.MOD_Modelo
        asset.TAC_Tipo_Activo = asset_type.TAC_Tipo_Activo
        asset.EOP_Estado_Operativo = state.EOP_Estado_Operativo
        if asset.ACT_Codigo_Interno != code and by_code is None:
            asset.ACT_Codigo_Interno = code
        stats["assets_updated"] += 1
    return asset


async def _upsert_specs(db: AsyncSession, asset: Activo, specs: dict[str, str], stats: Counter) -> None:
    units = {"RAM": "GB", "Almacenamiento": "GB"}
    for name, value in specs.items():
        spec_type = await _ensure_spec_type(db, name, units.get(name))
        existing = await _one(
            db,
            Especificacion,
            ACT_Activo=asset.ACT_Activo,
            TES_Tipo_Especificacion=spec_type.TES_Tipo_Especificacion,
        )
        if existing is None:
            db.add(Especificacion(
                ACT_Activo=asset.ACT_Activo,
                TES_Tipo_Especificacion=spec_type.TES_Tipo_Especificacion,
                ESP_Valor=_clip(value),
            ))
            stats["specs_created"] += 1
        else:
            existing.ESP_Valor = _clip(value)
            stats["specs_updated"] += 1


async def _ensure_open_movement(
    db: AsyncSession,
    asset: Activo,
    person: Persona,
    area: Area,
    movement_type: TipoMovimiento,
    record: InventoryRecord,
    stats: Counter,
) -> None:
    note = _clip(
        f"DATASET: custodia importada desde {record.file_name}; "
        f"usuario detectado: {record.username}; "
        f"fecha inventario: {record.generated_at.isoformat(sep=' ') if record.generated_at else 'N/D'}",
        1000,
    )
    existing = (await db.execute(
        select(Movimiento).where(
            Movimiento.ACT_Activo == asset.ACT_Activo,
            Movimiento.MOV_Fecha_Devolucion.is_(None),
        )
    )).scalar_one_or_none()
    if existing is None:
        db.add(Movimiento(
            ACT_Activo=asset.ACT_Activo,
            PER_Persona=person.PER_Persona,
            ARE_Area=area.ARE_Area,
            TMO_Tipo_Movimiento=movement_type.TMO_Tipo_Movimiento,
            MOV_Fecha_Asignacion=record.generated_at,
            MOV_Observacion=note,
        ))
        stats["movements_created"] += 1
        return

    if existing.MOV_Observacion and not existing.MOV_Observacion.startswith("DATASET:"):
        stats["movement_conflicts_skipped"] += 1
        return

    existing.PER_Persona = person.PER_Persona
    existing.ARE_Area = area.ARE_Area
    existing.TMO_Tipo_Movimiento = movement_type.TMO_Tipo_Movimiento
    existing.MOV_Fecha_Asignacion = record.generated_at or existing.MOV_Fecha_Asignacion
    existing.MOV_Observacion = note
    stats["movements_updated"] += 1


async def import_dataset(dataset_dir: Path, *, dry_run: bool, email_domain: str) -> dict[str, Any]:
    records = load_dataset(dataset_dir)
    host_counts = Counter(record.hostname for record in records)
    serial_counts = Counter(record.serial for record in records)
    duplicates = {
        "hostnames": sorted([key for key, count in host_counts.items() if count > 1]),
        "serials": sorted([key for key, count in serial_counts.items() if count > 1]),
    }
    if duplicates["hostnames"] or duplicates["serials"]:
        raise RuntimeError(f"Dataset has duplicate keys: {duplicates}")

    stats: Counter = Counter()
    generic_records: list[str] = []
    type_distribution = Counter(_asset_type_for(record.hostname)[0] for record in records)
    brand_distribution = Counter(record.brand for record in records)
    os_distribution = Counter(record.system_os for record in records)

    async with SessionLocal() as db:
        operator = await _operator(db)
        user_id = operator.USU_Usuario if operator else None
        users_area, staging_area = await _ensure_location(db)
        dep_users, _, cargo_user, _, staging_person = await _ensure_org(db)
        assigned_state = await _ensure_state(db, "Asignado")
        movement_type = await _ensure_movement_type(db, "Asignacion")

        for record in records:
            type_name, prefix = _asset_type_for(record.hostname)
            asset_type = await _ensure_type(db, type_name, prefix)
            brand = await _ensure_brand(db, record.brand)
            model = await _ensure_model(db, record, brand, asset_type)
            person, generic = await _ensure_person(
                db,
                record,
                dep_users,
                cargo_user,
                staging_person,
                email_domain,
                stats,
            )
            if generic:
                generic_records.append(record.hostname)
            asset = await _ensure_asset(db, record, model, asset_type, assigned_state, stats)
            await _upsert_specs(db, asset, _build_specs(record), stats)
            await _ensure_open_movement(
                db,
                asset,
                person,
                staging_area if generic else users_area,
                movement_type,
                record,
                stats,
            )

        await db.flush()
        # Alcance por sede: todo lo importado pertenece a la sede del dataset.
        sede_id = (await db.execute(
            select(Edificio.SED_Sede).join(Nivel, Nivel.EDI_Edificio == Edificio.EDI_Edificio)
            .where(Nivel.NIV_Nivel == users_area.NIV_Nivel)
        )).scalar_one()
        for model_cls in (Activo, Persona):
            await db.execute(
                update(model_cls).where(model_cls.SED_Sede.is_(None)).values(SED_Sede=sede_id)
                .execution_options(synchronize_session=False)
            )
        total_dataset_assets = (await db.execute(
            select(func.count()).select_from(Activo).where(
                Activo.ACT_Hostname.in_([record.hostname for record in records])
            )
        )).scalar_one()
        open_movements = (await db.execute(
            select(func.count()).select_from(Movimiento)
            .join(Activo, Activo.ACT_Activo == Movimiento.ACT_Activo)
            .where(
                Activo.ACT_Hostname.in_([record.hostname for record in records]),
                Movimiento.MOV_Fecha_Devolucion.is_(None),
            )
        )).scalar_one()

        report = {
            "dry_run": dry_run,
            "dataset_dir": str(dataset_dir),
            "files": len(records),
            "quality": {
                "duplicates": duplicates,
                "generic_user_hostnames": generic_records,
                "missing_generated_at": [record.hostname for record in records if record.generated_at is None],
                "purchase_date_policy": "ACT_Fecha_Compra uses inventory report date because dataset has no real purchase date.",
            },
            "distribution": {
                "types": dict(type_distribution),
                "brands": dict(brand_distribution),
                "os": dict(os_distribution),
            },
            "changes": dict(stats),
            "post_import_view": {
                "dataset_assets_by_hostname": int(total_dataset_assets),
                "open_custody_movements": int(open_movements),
            },
            "samples": [
                {
                    "hostname": record.hostname,
                    "serial": record.serial,
                    "user": record.username,
                    "person": record.display_name or ("TI Staging" if _is_generic_user(record) else record.username),
                    "model": record.model,
                    "os": record.system_os,
                }
                for record in records[:5]
            ],
        }

        db.add(AuditoriaSistema(
            AUD_Accion="DATASET_IMPORT_DRY_RUN" if dry_run else "DATASET_IMPORT",
            AUD_Entidad_Afectada=IMPORT_ENTITY,
            AUD_Snapshot_JSON=report,
            USU_Usuario=user_id,
            AUD_IP_Origen="127.0.0.1",
            AUD_User_Agent=IMPORT_AGENT,
        ))

        if dry_run:
            await db.rollback()
        else:
            await db.commit()
        return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Lombardi inventory dataset HTML files.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("../dataset"),
        help="Directory containing inventory HTML files.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and rollback changes.")
    parser.add_argument(
        "--email-domain",
        default=DEFAULT_EMAIL_DOMAIN,
        help="Synthetic email domain for imported employee identities.",
    )
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


if __name__ == "__main__":
    args = parse_args()
    result = asyncio.run(
        import_dataset(
            args.dataset.resolve(),
            dry_run=args.dry_run,
            email_domain=args.email_domain,
        )
    )
    log.info("Dataset inventory import completed. dry_run=%s files=%s", args.dry_run, result["files"])
    print(json.dumps(result, indent=2, ensure_ascii=False, default=_json_default))
