"""Generación de etiquetas imprimibles (QR) para activos."""
from __future__ import annotations

from io import BytesIO
import uuid

import qrcode
from fastapi import HTTPException
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Activo
from app.services.report_i18n import normalize_lang

# Textos de la etiqueta por idioma (espacio reducido: 7 pt, ~30 caracteres).
_LABEL_TEXTS = {
    "es": {"serial": "N.º de serie", "title": "Etiquetas de activos", "filename": "etiquetas-activos"},
    "en": {"serial": "Serial no.", "title": "Asset labels", "filename": "asset-labels"},
    "it": {"serial": "N. di serie", "title": "Etichette degli asset", "filename": "etichette-asset"},
}


def label_filename(lang: str | None) -> str:
    return f"{_LABEL_TEXTS[normalize_lang(lang)]['filename']}.pdf"


class LabelService:
    """Crea hojas carta con etiquetas QR en cuadrícula tipo Avery 5160."""

    MAX_LABELS_PER_BATCH = 200

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _load_assets(
        self,
        *,
        activo_ids: list[uuid.UUID] | None,
        codigos: list[str] | None,
    ) -> list[Activo]:
        conditions = []
        if activo_ids:
            conditions.append(Activo.ACT_Activo.in_(activo_ids))
        if codigos:
            normalized_codes = [codigo.strip() for codigo in codigos if codigo.strip()]
            if normalized_codes:
                conditions.append(Activo.ACT_Codigo_Interno.in_(normalized_codes))
        if not conditions:
            raise HTTPException(400, detail="LABEL_ASSETS_REQUIRED")

        from sqlalchemy import or_

        rows = (await self.db.execute(
            select(Activo)
            .where(or_(*conditions))
            .order_by(Activo.ACT_Codigo_Interno.asc())
        )).scalars().all()

        if not rows:
            raise HTTPException(404, detail="ASSETS_NOT_FOUND")
        if len(rows) > self.MAX_LABELS_PER_BATCH:
            raise HTTPException(400, detail="TOO_MANY_LABELS_REQUESTED")
        return rows

    @staticmethod
    def _qr_image(value: str) -> ImageReader:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=2,
        )
        qr.add_data(value)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return ImageReader(buffer)

    async def generar_pdf_etiquetas(
        self,
        *,
        activo_ids: list[uuid.UUID] | None = None,
        codigos: list[str] | None = None,
        lang: str | None = "es",
    ) -> BytesIO:
        activos = await self._load_assets(activo_ids=activo_ids, codigos=codigos)
        texts = _LABEL_TEXTS[normalize_lang(lang)]

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=letter)
        pdf.setTitle(texts["title"])
        page_width, page_height = letter

        columns = 3
        rows = 10
        label_width = 2.625 * inch
        label_height = 1.0 * inch
        left_margin = 0.1875 * inch
        top_margin = 0.5 * inch
        col_gap = 0.125 * inch
        qr_size = 0.68 * inch

        for idx, activo in enumerate(activos):
            page_pos = idx % (columns * rows)
            if idx and page_pos == 0:
                pdf.showPage()

            row = page_pos // columns
            col = page_pos % columns
            x = left_margin + col * (label_width + col_gap)
            y_top = page_height - top_margin - row * label_height
            y = y_top - label_height

            code = activo.ACT_Codigo_Interno
            pdf.drawImage(
                self._qr_image(code),
                x + 0.08 * inch,
                y + 0.16 * inch,
                width=qr_size,
                height=qr_size,
                preserveAspectRatio=True,
                mask="auto",
            )

            text_x = x + 0.84 * inch
            pdf.setFont("Helvetica-Bold", 10)
            pdf.drawString(text_x, y + 0.68 * inch, code[:24])
            pdf.setFont("Helvetica", 7)
            if activo.ACT_Hostname:
                pdf.drawString(text_x, y + 0.48 * inch, activo.ACT_Hostname[:30])
            max_w = label_width - 0.9 * inch
            serial_line = f"{texts['serial']}: {activo.ACT_Serie_Fabricante or ''}"
            while len(serial_line) > 1 and pdf.stringWidth(serial_line, "Helvetica", 7) > max_w:
                serial_line = serial_line[:-1]
            pdf.drawString(text_x, y + 0.30 * inch, serial_line)

        pdf.save()
        buffer.seek(0)
        return buffer
