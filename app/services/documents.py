"""
Generación de Actas de Entrega / Hojas de Descargo en Word (.docx) y PDF.

El formato reproduce el acta corporativa de referencia (ejemplo.pdf):
  · Encabezado: logo (izq) + código de formulario y "Ciudad, fecha" (der).
  · Título centrado en negrita: "NOTA: ENTREGA…" / "NOTA: DEVOLUCIÓN A …".
  · Párrafo de respaldo + tabla DISPOSITIVO | MARCA | MODELO | SERIE con
    cabecera oscura y texto blanco.
  · Párrafos de casuística + "Descripción: <motivo>".
  · Dos firmas (Entrega / Recibe) con nombre, rol, departamento y empresa.
  · Pie de página legal en letra pequeña.

Si el logo no se puede descargar, se degrada al nombre de la empresa en texto.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from io import BytesIO
from datetime import datetime
from typing import List, Optional
import uuid
from urllib.parse import urljoin, urlparse
from xml.sax.saxutils import escape as _xml_escape

import httpx
import structlog
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.traceability import TraceabilityRepository
from app.repositories.governance import GovernanceRepository
from app.services.report_i18n import (
    MONTHS,
    format_long_date,
    normalize_lang,
    translate_catalog,
)

log = structlog.get_logger("documents")

# Paleta corporativa del acta de referencia.
_HEADER_BG = (31, 58, 95)     # navy de la cabecera de la tabla
_INK = (15, 23, 42)
_MUTED = (90, 100, 115)
_DEFAULT_PRIMARY = (31, 58, 95)

# Datos institucionales del encabezado (configurables a futuro).
_CIUDAD = "Guatemala"
_CODIGO_FORM = "F.IT.GUA.04.01"

_MAX_LOGO_BYTES = 3_000_000
_MAX_LOGO_REDIRECTS = 3
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

_MESES_BY_LANG = MONTHS

# Textos del acta. El registro es formal/administrativo en los tres idiomas.
# Los títulos en español reproducen el formulario corporativo de referencia.
_ACTA_TEXTS_BY_LANG = {
    "es": {
        "entrega": {
            "titulo": "NOTA: ENTREGA DE EQUIPO",
            "intro": ("El presente documento se extiende como respaldo de la entrega de dispositivos "
                      "propiedad de {empresa} al colaborador {colaborador}, y en él se detallan las "
                      "características de los dispositivos entregados."),
            "cuerpo": ("Se emite para conocimiento y respaldo de la administración. Los activos de la "
                       "empresa aquí descritos quedan bajo la custodia y responsabilidad del "
                       "colaborador, quien se compromete a darles un uso adecuado y a devolverlos "
                       "cuando la empresa así lo requiera."),
            "firma_izq": ("Recibe el equipo", "Colaborador"),
            "firma_der": ("Entrega y autoriza", "Departamento de TI"),
        },
        "descargo": {
            "titulo": "NOTA: DEVOLUCIÓN A {empresa}",
            "intro": ("El presente documento se extiende como respaldo de la devolución de "
                      "dispositivos a {empresa}, y en él se detallan las características de los "
                      "dispositivos recibidos."),
            "cuerpo": ("Se emite para conocimiento y respaldo de la administración, y hace constar la "
                       "recepción de los activos de la empresa por causas tales como daño, "
                       "obsolescencia del equipo, equipo propiedad del colaborador y/o caso especial "
                       "autorizado."),
            "firma_izq": ("Entrega el equipo", "Colaborador"),
            "firma_der": ("Recibe", "Departamento de TI"),
        },
    },
    "en": {
        "entrega": {
            "titulo": "NOTE: EQUIPMENT HANDOVER",
            "intro": ("This document is issued as a record of the handover of devices owned by "
                      "{empresa} to employee {colaborador}, and it describes the devices delivered."),
            "cuerpo": ("It is issued for the information and records of management. The company assets "
                       "described herein remain in the custody and under the responsibility of the "
                       "employee, who undertakes to use them appropriately and to return them whenever "
                       "the company so requires."),
            "firma_izq": ("Received by", "Employee"),
            "firma_der": ("Delivered and authorized by", "IT Department"),
        },
        "descargo": {
            "titulo": "NOTE: RETURN OF EQUIPMENT TO {empresa}",
            "intro": ("This document is issued as a record of the return of devices to {empresa}, "
                      "and it describes the devices received."),
            "cuerpo": ("It is issued for the information and records of management, and it certifies "
                       "the receipt of company assets for reasons such as damage, obsolescence, "
                       "employee-owned equipment and/or a specially authorized case."),
            "firma_izq": ("Returned by", "Employee"),
            "firma_der": ("Received by", "IT Department"),
        },
    },
    "it": {
        "entrega": {
            "titulo": "NOTA: CONSEGNA DI APPARECCHIATURE",
            "intro": ("Il presente documento viene redatto a comprova della consegna di dispositivi "
                      "di proprietà di {empresa} al collaboratore {colaborador} e ne riporta le "
                      "caratteristiche."),
            "cuerpo": ("Viene emesso per conoscenza e a supporto dell'amministrazione. I beni aziendali "
                       "qui descritti sono affidati alla custodia e alla responsabilità del "
                       "collaboratore, che si impegna a farne un uso appropriato e a restituirli su "
                       "richiesta dell'azienda."),
            "firma_izq": ("Riceve l'apparecchiatura", "Collaboratore"),
            "firma_der": ("Consegna e autorizza", "Reparto IT"),
        },
        "descargo": {
            "titulo": "NOTA: RESTITUZIONE DI APPARECCHIATURE A {empresa}",
            "intro": ("Il presente documento viene redatto a comprova della restituzione di "
                      "dispositivi a {empresa} e ne riporta le caratteristiche."),
            "cuerpo": ("Viene emesso per conoscenza e a supporto dell'amministrazione e attesta la "
                       "ricezione dei beni aziendali per motivi quali danneggiamento, obsolescenza, "
                       "apparecchiatura di proprietà del collaboratore e/o caso speciale autorizzato."),
            "firma_izq": ("Restituisce l'apparecchiatura", "Collaboratore"),
            "firma_der": ("Riceve", "Reparto IT"),
        },
    },
}

_LABELS_BY_LANG = {
    "es": {
        "device": "DISPOSITIVO",
        "brand": "MARCA",
        "model": "MODELO",
        "serial": "SERIE",
        "description": "Descripción",
        "external_messenger": "Mensajero externo",
        "not_company": "No pertenece a {empresa}",
    },
    "en": {
        "device": "DEVICE",
        "brand": "BRAND",
        "model": "MODEL",
        "serial": "SERIAL NUMBER",
        "description": "Description",
        "external_messenger": "External courier",
        "not_company": "Not affiliated with {empresa}",
    },
    "it": {
        "device": "DISPOSITIVO",
        "brand": "MARCA",
        "model": "MODELLO",
        "serial": "NUMERO DI SERIE",
        "description": "Descrizione",
        "external_messenger": "Corriere esterno",
        "not_company": "Esterno a {empresa}",
    },
}

_DEFAULT_REASON_BY_LANG = {
    "es": {"entrega": "Asignación de equipo.", "descargo": "Devolución de equipo."},
    "en": {"entrega": "Equipment assignment.", "descargo": "Equipment return."},
    "it": {"entrega": "Assegnazione di apparecchiature.", "descargo": "Restituzione di apparecchiature."},
}

_PIE_LEGAL_BY_LANG = {
    "es": (
        "Este documento debe ser escaneado y enviado por correo electrónico a la administración y a "
        "las jefaturas relacionadas con la adquisición y el retiro de equipos informáticos, ya sean "
        "activos propios de la empresa o de terceros. {empresa} no se hace responsable del uso "
        "indebido que se dé al equipo fuera de sus instalaciones. Este documento no constituye un "
        "instrumento legal; se emite únicamente para control interno y conocimiento de las partes "
        "involucradas, y es de uso exclusivo de {empresa}."
    ),
    "en": (
        "This document must be scanned and sent by email to the administration and to the managers "
        "involved in the acquisition and withdrawal of IT equipment, whether owned by the company or "
        "by third parties. {empresa} is not liable for any misuse of the equipment outside its "
        "premises. This document is not a legal instrument; it is issued solely for internal control "
        "and for the information of the parties involved, and is for the exclusive use of {empresa}."
    ),
    "it": (
        "Il presente documento deve essere scansionato e inviato via e-mail all'amministrazione e ai "
        "responsabili coinvolti nell'acquisizione e nel ritiro delle apparecchiature informatiche, "
        "siano esse di proprietà dell'azienda o di terzi. {empresa} declina ogni responsabilità per "
        "l'uso improprio delle apparecchiature al di fuori dei propri locali. Il presente documento "
        "non costituisce un atto avente valore legale; è emesso esclusivamente per il controllo "
        "interno e per conoscenza delle parti coinvolte, ed è a uso esclusivo di {empresa}."
    ),
}

_WORD_LANG_TAGS = {"es": "es-GT", "en": "en-US", "it": "it-IT"}

# Nombre base del archivo descargado, por idioma y tipo de acta.
ACTA_FILENAMES_BY_LANG = {
    "es": {"entrega": "Acta_Entrega", "descargo": "Acta_Descargo"},
    "en": {"entrega": "Handover_Record", "descargo": "Return_Record"},
    "it": {"entrega": "Verbale_Consegna", "descargo": "Verbale_Restituzione"},
}

# Compatibilidad para pruebas y consumidores internos antiguos.
_MESES = _MESES_BY_LANG["es"]
_ACTA_TEXTS = _ACTA_TEXTS_BY_LANG["es"]
_PIE_LEGAL = _PIE_LEGAL_BY_LANG["es"]

# Formas societarias: si el nombre ya termina en una, no se añade "S.A.".
_LEGAL_SUFFIXES = ("s.a.", "s.a", "sa", "s.a.s.", "s.r.l.", "srl", "s.p.a.", "spa", "inc.", "inc",
                   "ltd.", "ltd", "llc", "s. de r.l.", "s.a. de c.v.", "gmbh")


def _normalize_lang(lang: str | None) -> str:
    return normalize_lang(lang)


def _format_fecha_larga(value: datetime, lang: str) -> str:
    return format_long_date(value, lang)


def _razon_social(empresa: str) -> str:
    """Nombre legal para el cuerpo del acta: añade 'S.A.' salvo que ya tenga forma societaria."""
    name = empresa.strip()
    lowered = name.lower().rstrip(",")
    if any(lowered.endswith(" " + suf) or lowered.endswith("," + suf) for suf in _LEGAL_SUFFIXES):
        return name
    return f"{name} S.A."


def acta_filename(tipo: str, lang: str | None) -> str:
    names = ACTA_FILENAMES_BY_LANG[normalize_lang(lang)]
    return names.get(tipo, names["entrega"])


class DocumentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.trace_repo = TraceabilityRepository(db)
        self.gov_repo = GovernanceRepository(db)

    # =================================================================
    # API PÚBLICA
    # =================================================================
    async def generar_acta_entrega(self, movimiento_id: uuid.UUID, formato: str = "docx",
                                   tipo: str = "entrega", mensajero: Optional[str] = None,
                                   lang: str = "es") -> BytesIO:
        data = await self._gather([movimiento_id], tipo=tipo, mensajero=mensajero, lang=lang)
        return self._render(data, formato)

    async def generar_acta_multiple(self, movimiento_ids: List[uuid.UUID], formato: str = "docx",
                                    tipo: str = "entrega", mensajero: Optional[str] = None,
                                    lang: str = "es") -> BytesIO:
        data = await self._gather(movimiento_ids, tipo=tipo, mensajero=mensajero, lang=lang)
        return self._render(data, formato)

    def _render(self, data: dict, formato: str) -> BytesIO:
        return self._render_pdf(data) if (formato or "").lower() == "pdf" else self._render_docx(data)

    # =================================================================
    # RECOLECCIÓN DE DATOS
    # =================================================================
    async def _gather(self, movimiento_ids: List[uuid.UUID], tipo: str = "entrega",
                      mensajero: Optional[str] = None, lang: str = "es") -> dict:
        lang = _normalize_lang(lang)
        tipo = tipo if tipo in _ACTA_TEXTS_BY_LANG[lang] else "entrega"
        txt = _ACTA_TEXTS_BY_LANG[lang][tipo]
        labels = _LABELS_BY_LANG[lang]
        movimientos = []
        for mid in movimiento_ids:
            mov = await self.trace_repo.get_by_id_full(mid)
            if not mov:
                raise HTTPException(status_code=404, detail=f"MOVEMENT_NOT_FOUND: {mid}")
            movimientos.append(mov)
        if not movimientos:
            raise HTTPException(status_code=400, detail="NO_MOVEMENTS_PROVIDED")

        persona = movimientos[0].persona
        for mov in movimientos:
            if mov.PER_Persona != persona.PER_Persona:
                raise HTTPException(status_code=400, detail="CANNOT_MIX_DIFFERENT_PEOPLE_IN_SAME_DOCUMENT")

        config = await self.gov_repo.get_config()
        empresa = (config.SYS_Nombre_Empresa or "Mi Empresa").strip()
        logo = await self._fetch_logo(config.SYS_Logo_URL)

        items = []
        for mov in movimientos:
            a = mov.activo
            tipo_act = (translate_catalog("tipo_activo", a.tipo_activo.TAC_Nombre, lang)
                        if a and a.tipo_activo else "")
            marca = a.modelo.marca.MAR_Nombre if a and a.modelo and a.modelo.marca else ""
            modelo = a.modelo.MOD_Nombre if a and a.modelo else ""
            hostname = (a.ACT_Hostname if a else "") or ""
            # "DISPOSITIVO" = hostname si existe, si no el tipo, si no el código.
            dispositivo = hostname or tipo_act or (a.ACT_Codigo_Interno if a else "—")
            items.append({
                "dispositivo": dispositivo or "—",
                "marca": (marca or "—").upper(),
                "modelo": modelo or "—",
                "serie": (a.ACT_Serie_Fabricante if a else "") or "—",
            })

        if tipo == "descargo" and movimientos[0].MOV_Fecha_Devolucion:
            d = movimientos[0].MOV_Fecha_Devolucion
        else:
            d = datetime.now()
        motivo_default = _DEFAULT_REASON_BY_LANG[lang][tipo]

        return {
            "tipo": tipo,
            "lang": lang,
            "txt": txt,
            "labels": labels,
            "pie_legal": _PIE_LEGAL_BY_LANG[lang],
            "empresa": empresa,
            "logo": logo,
            "primary": self._hex_to_rgb(config.SYS_Color_Primario, _DEFAULT_PRIMARY),
            "colaborador": f"{persona.PER_Primer_Nombre} {persona.PER_Primer_Apellido}".strip(),
            "mensajero": (mensajero or "").strip() or None,
            "ciudad": (config.SYS_Ciudad or _CIUDAD).strip(),
            "codigo_form": (config.SYS_Codigo_Formulario or _CODIGO_FORM).strip(),
            "fecha_larga": _format_fecha_larga(d, lang),
            "acta_ref": str(movimientos[0].MOV_Movimiento)[:8].upper(),
            "motivo": movimientos[0].MOV_Observacion or motivo_default,
            "items": items,
        }

    async def _fetch_logo(self, url: Optional[str]) -> Optional[bytes]:
        if not url or not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
            return None
        current_url = url.strip()
        try:
            if not await self._is_safe_logo_url(current_url):
                log.warning("documents.logo_url_blocked", target=self._safe_url_for_log(current_url))
                return None

            async with httpx.AsyncClient(timeout=4.0, follow_redirects=False) as client:
                for _ in range(_MAX_LOGO_REDIRECTS + 1):
                    async with client.stream("GET", current_url, headers={"Accept": "image/*"}) as r:
                        if r.status_code in _REDIRECT_STATUSES:
                            location = r.headers.get("location")
                            if not location:
                                return None
                            current_url = urljoin(current_url, location)
                            if not await self._is_safe_logo_url(current_url):
                                log.warning(
                                    "documents.logo_url_blocked",
                                    target=self._safe_url_for_log(current_url),
                                )
                                return None
                            continue

                        ct = r.headers.get("content-type", "").lower()
                        if r.status_code != 200 or not ct.startswith("image/"):
                            return None

                        content_length = r.headers.get("content-length")
                        if content_length and int(content_length) > _MAX_LOGO_BYTES:
                            return None

                        content = bytearray()
                        async for chunk in r.aiter_bytes():
                            content.extend(chunk)
                            if len(content) > _MAX_LOGO_BYTES:
                                return None
                        return bytes(content) if content else None
                log.warning("documents.logo_redirect_limit", target=self._safe_url_for_log(current_url))
        except Exception as e:  # noqa: BLE001
            log.warning("documents.logo_fetch_failed", error=str(e)[:160])
        return None

    @staticmethod
    def _is_public_ip(value: str) -> bool:
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            return False
        return bool(ip.is_global and not ip.is_multicast)

    @staticmethod
    async def _is_safe_logo_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            scheme = parsed.scheme.lower()
            host = parsed.hostname
            port = parsed.port
        except ValueError:
            return False

        if scheme not in {"http", "https"} or not host:
            return False
        if parsed.username or parsed.password:
            return False
        if port not in {None, 80, 443}:
            return False

        host = host.strip("[]").rstrip(".").lower()
        if host == "localhost" or host.endswith(".localhost"):
            return False

        if DocumentService._is_public_ip(host):
            return True
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass

        try:
            infos = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                port or (443 if scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except OSError:
            return False

        ips = {info[4][0] for info in infos if info and info[4]}
        return bool(ips) and all(DocumentService._is_public_ip(ip) for ip in ips)

    @staticmethod
    def _safe_url_for_log(url: str) -> str:
        try:
            parsed = urlparse(url)
        except ValueError:
            return "invalid-url"
        host = parsed.hostname or "unknown-host"
        return f"{parsed.scheme}://{host}"

    @staticmethod
    def _hex_to_rgb(h: Optional[str], default: tuple = _DEFAULT_PRIMARY) -> tuple:
        s = (h or "").lstrip("#")
        try:
            if len(s) == 6:
                return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
            if len(s) == 3:
                return tuple(int(s[i] * 2, 16) for i in range(3))
        except ValueError:
            pass
        return default

    @staticmethod
    def _logo_size_inches(img_bytes: bytes, max_w: float, max_h: float) -> Optional[tuple]:
        try:
            from PIL import Image as PILImage
            with PILImage.open(BytesIO(img_bytes)) as im:
                w, h = im.size
            if w <= 0 or h <= 0:
                return None
            scale = min(max_w / w, max_h / h)
            return (w * scale, h * scale)
        except Exception:  # noqa: BLE001
            return None

    # =================================================================
    # RENDER WORD (.docx)
    # =================================================================
    def _render_docx(self, data: dict) -> BytesIO:
        from docx import Document
        from docx.shared import Pt, RGBColor, Inches
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_ALIGN_VERTICAL
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        empresa = data["empresa"]
        txt = data["txt"]
        labels = data.get("labels", _LABELS_BY_LANG["es"])
        header_hex = "%02X%02X%02X" % _HEADER_BG

        def shade(cell, hex_color):
            tcPr = cell._tc.get_or_add_tcPr()
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_color)
            tcPr.append(shd)

        def no_borders(tbl):
            borders = OxmlElement("w:tblBorders")
            for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
                e = OxmlElement(f"w:{edge}"); e.set(qn("w:val"), "none"); borders.append(e)
            tbl._tbl.tblPr.append(borders)

        doc = Document()
        st = doc.styles["Normal"]; st.font.name = "Arial"; st.font.size = Pt(11)
        # Idioma de corrección ortográfica de Word acorde al idioma del acta.
        word_lang = _WORD_LANG_TAGS.get(data.get("lang", "es"), "es-ES")
        rpr = st.element.get_or_add_rPr()
        lang_el = OxmlElement("w:lang")
        lang_el.set(qn("w:val"), word_lang); lang_el.set(qn("w:eastAsia"), word_lang)
        rpr.append(lang_el)
        props = doc.core_properties
        props.title = f"{txt['titulo'].format(empresa=empresa)} {data.get('acta_ref', '')}".strip()
        props.author = empresa
        props.language = word_lang
        for s in doc.sections:
            s.top_margin = Inches(0.8); s.bottom_margin = Inches(0.7)
            s.left_margin = Inches(0.9); s.right_margin = Inches(0.9)

        # --- ENCABEZADO: logo (izq) + código/fecha (der) ---
        head = doc.add_table(rows=1, cols=2); no_borders(head)
        head.columns[0].width = Inches(3.4); head.columns[1].width = Inches(3.4)
        cl, cr = head.rows[0].cells
        cl.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        cr.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        pl = cl.paragraphs[0]; pl.alignment = WD_ALIGN_PARAGRAPH.LEFT
        placed = False
        if data["logo"]:
            size = self._logo_size_inches(data["logo"], max_w=2.6, max_h=1.0)
            if size:
                try:
                    pl.add_run().add_picture(BytesIO(data["logo"]), width=Inches(size[0]), height=Inches(size[1]))
                    placed = True
                except Exception:  # noqa: BLE001
                    placed = False
        if not placed:
            r = pl.add_run(empresa); r.bold = True; r.font.size = Pt(22); r.font.color.rgb = RGBColor(*_HEADER_BG)
        pr = cr.paragraphs[0]; pr.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r1 = pr.add_run(data["codigo_form"]); r1.bold = True; r1.font.size = Pt(10)
        r2 = pr.add_run(f"\n{data['ciudad']}, {data['fecha_larga']}"); r2.font.size = Pt(10)

        doc.add_paragraph()
        # --- TÍTULO ---
        ti = doc.add_paragraph(); ti.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rt = ti.add_run(txt["titulo"].format(empresa=empresa.upper())); rt.bold = True; rt.font.size = Pt(12)
        doc.add_paragraph()

        # --- INTRO ---
        intro = doc.add_paragraph(); intro.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        intro.add_run(txt["intro"].format(empresa=_razon_social(empresa), colaborador=data["colaborador"]))
        doc.add_paragraph()

        # --- TABLA ---
        headers = [labels["device"], labels["brand"], labels["model"], labels["serial"]]
        table = doc.add_table(rows=1, cols=4); table.style = "Table Grid"
        table.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for i, h in enumerate(headers):
            c = table.rows[0].cells[i]; shade(c, header_hex)
            p = c.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            rr = p.add_run(h); rr.bold = True; rr.font.size = Pt(10); rr.font.color.rgb = RGBColor(255, 255, 255)
        for it in data["items"]:
            cells = table.add_row().cells
            for i, key in enumerate(("dispositivo", "marca", "modelo", "serie")):
                p = cells[i].paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.add_run(str(it[key])).font.size = Pt(10)
        doc.add_paragraph()

        # --- CUERPO ---
        cu = doc.add_paragraph(); cu.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        cu.add_run(txt["cuerpo"])
        de = doc.add_paragraph(); de.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        de.add_run(f"{labels['description']}: ").bold = True
        de.add_run(data["motivo"])

        for _ in range(5):
            doc.add_paragraph()

        # --- FIRMAS ---
        fz, fd = txt["firma_izq"], txt["firma_der"]
        # Firma derecha: Departamento de TI; si hay mensajero externo, lo recibe él.
        if data.get("mensajero"):
            der_sig = (
                data["mensajero"],
                fd[0],
                labels["external_messenger"],
                labels["not_company"].format(empresa=empresa),
            )
        else:
            der_sig = ("", fd[0], fd[1], empresa)
        ft = doc.add_table(rows=1, cols=2); no_borders(ft)
        izq, der = ft.rows[0].cells
        for cell, (nombre, accion, depto, comp) in (
            (izq, (data["colaborador"], fz[0], fz[1], empresa)),
            (der, der_sig),
        ):
            p = cell.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run("_______________________________\n").bold = False
            if nombre:
                rn = p.add_run(nombre + "\n"); rn.bold = True; rn.font.size = Pt(10.5)
            p.add_run(accion + "\n").font.size = Pt(10)
            rd = p.add_run(depto + "\n"); rd.bold = True; rd.font.size = Pt(10)
            re = p.add_run(comp); re.font.size = Pt(9.5); re.font.color.rgb = RGBColor(*_MUTED)

        for _ in range(2):
            doc.add_paragraph()
        # --- PIE LEGAL ---
        pie = doc.add_paragraph(); pie.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        rp = pie.add_run("•  " + data.get("pie_legal", _PIE_LEGAL_BY_LANG["es"]).format(empresa=empresa))
        rp.font.size = Pt(7.5); rp.font.color.rgb = RGBColor(*_MUTED)

        buf = BytesIO(); doc.save(buf); buf.seek(0)
        return buf

    # =================================================================
    # RENDER PDF (reportlab)
    # =================================================================
    def _render_pdf(self, data: dict) -> BytesIO:
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_JUSTIFY, TA_RIGHT, TA_CENTER, TA_LEFT
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage,
        )

        # reportlab interpreta mini-HTML en Paragraph: los datos del usuario
        # (nombres, motivo, empresa) se escapan para que '&' o '<' no rompan el PDF.
        esc = lambda v: _xml_escape(str(v))  # noqa: E731
        empresa_raw = data["empresa"]
        empresa = esc(empresa_raw)
        txt = data["txt"]
        labels = data.get("labels", _LABELS_BY_LANG["es"])
        header_bg = colors.Color(*[c / 255 for c in _HEADER_BG])
        ink = colors.Color(*[c / 255 for c in _INK])
        muted = colors.Color(*[c / 255 for c in _MUTED])

        ss = getSampleStyleSheet()
        st_code = ParagraphStyle("code", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=10,
                                 alignment=TA_RIGHT, textColor=ink, leading=14)
        st_date = ParagraphStyle("date", parent=ss["Normal"], fontSize=10, alignment=TA_RIGHT, textColor=ink)
        st_title = ParagraphStyle("title", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=12,
                                  alignment=TA_CENTER, textColor=ink, leading=16)
        st_body = ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica", fontSize=10.5,
                                 alignment=TA_JUSTIFY, leading=15)
        st_cellh = ParagraphStyle("ch", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=9.5,
                                  textColor=colors.white, alignment=TA_CENTER, leading=12)
        st_cell = ParagraphStyle("cl", parent=ss["Normal"], fontSize=9.5, alignment=TA_CENTER, leading=12)
        st_sign = ParagraphStyle("sg", parent=ss["Normal"], fontSize=10, alignment=TA_CENTER, leading=14)
        st_foot = ParagraphStyle("ft", parent=ss["Normal"], fontSize=7.5, alignment=TA_JUSTIFY,
                                 textColor=muted, leading=10)
        st_brand = ParagraphStyle("br", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=22,
                                  textColor=header_bg, alignment=TA_LEFT)

        story = []

        # --- ENCABEZADO ---
        logo_flow = None
        if data["logo"]:
            size = self._logo_size_inches(data["logo"], max_w=2.6, max_h=1.0)
            if size:
                try:
                    logo_flow = RLImage(BytesIO(data["logo"]), width=size[0] * inch, height=size[1] * inch)
                    logo_flow.hAlign = "LEFT"
                except Exception:  # noqa: BLE001
                    logo_flow = None
        if logo_flow is None:
            logo_flow = Paragraph(empresa, st_brand)
        right = [Paragraph(esc(data["codigo_form"]), st_code),
                 Paragraph(esc(f"{data['ciudad']}, {data['fecha_larga']}"), st_date)]
        header = Table([[logo_flow, right]], colWidths=[3.4 * inch, 3.4 * inch])
        header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                    ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(header)
        story.append(Spacer(1, 22))

        # --- TÍTULO ---
        story.append(Paragraph(txt["titulo"].format(empresa=esc(empresa_raw.upper())), st_title))
        story.append(Spacer(1, 18))

        # --- INTRO ---
        story.append(Paragraph(
            txt["intro"].format(empresa=esc(_razon_social(empresa_raw)),
                                colaborador=f"<b>{esc(data['colaborador'])}</b>"),
            st_body))
        story.append(Spacer(1, 14))

        # --- TABLA ---
        tdata = [[Paragraph(h, st_cellh) for h in (labels["device"], labels["brand"], labels["model"], labels["serial"])]]
        for it in data["items"]:
            tdata.append([Paragraph(esc(it["dispositivo"]), st_cell),
                          Paragraph(esc(it["marca"]), st_cell),
                          Paragraph(esc(it["modelo"]), st_cell),
                          Paragraph(esc(it["serie"]), st_cell)])
        tbl = Table(tdata, colWidths=[1.9 * inch, 1.35 * inch, 1.85 * inch, 1.65 * inch], repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), header_bg),
            ("GRID", (0, 0), (-1, -1), 0.7, colors.Color(0.55, 0.6, 0.68)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 16))

        # --- CUERPO ---
        story.append(Paragraph(txt["cuerpo"], st_body))
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"<b>{labels['description']}:</b> {esc(data['motivo'])}", st_body))
        story.append(Spacer(1, 66))

        # --- FIRMAS ---
        fz, fd = txt["firma_izq"], txt["firma_der"]
        co_style = ParagraphStyle("co", parent=st_sign, fontSize=9.5, textColor=muted)

        def firma(nombre, accion, depto, comp):
            out = [Paragraph("_______________________________", st_sign)]
            if nombre:
                out.append(Paragraph(f"<b>{esc(nombre)}</b>", st_sign))
            out.append(Paragraph(accion, st_sign))
            out.append(Paragraph(f"<b>{depto}</b>", st_sign))
            out.append(Paragraph(comp, co_style))
            return out

        if data.get("mensajero"):
            der_sig = firma(
                data["mensajero"],
                fd[0],
                labels["external_messenger"],
                labels["not_company"].format(empresa=empresa),
            )
        else:
            der_sig = firma("", fd[0], fd[1], empresa)
        firmas = Table([[firma(data["colaborador"], fz[0], fz[1], empresa), der_sig]],
                       colWidths=[3.35 * inch, 3.35 * inch])
        firmas.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(firmas)
        story.append(Spacer(1, 30))

        # --- PIE LEGAL ---
        story.append(Paragraph("•&nbsp;&nbsp;" + data.get("pie_legal", _PIE_LEGAL_BY_LANG["es"]).format(empresa=empresa), st_foot))

        buf = BytesIO()
        pdf = SimpleDocTemplate(buf, pagesize=LETTER, topMargin=0.8 * inch, bottomMargin=0.7 * inch,
                                leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                                title=f"{txt['titulo'].format(empresa=empresa_raw)} {data['acta_ref']}",
                                author=empresa_raw, lang=data.get("lang", "es"))
        pdf.build(story)
        buf.seek(0)
        return buf
