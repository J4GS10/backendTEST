from io import BytesIO
from datetime import datetime
from typing import List
import uuid
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fastapi import HTTPException

from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.traceability import TraceabilityRepository
from app.repositories.governance import GovernanceRepository

class DocumentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.trace_repo = TraceabilityRepository(db)
        self.gov_repo = GovernanceRepository(db)

    # =================================================================
    # MÉTODO 1: ACTA INDIVIDUAL (El que faltaba)
    # =================================================================
    async def generar_acta_entrega(self, movimiento_id: uuid.UUID) -> BytesIO:
        """
        Genera un archivo .docx profesional con los datos de UN movimiento.
        """
        # 1. Obtener Datos
        movimiento = await self.trace_repo.get_by_id_full(movimiento_id)
        
        if not movimiento:
            raise HTTPException(status_code=404, detail="MOVEMENT_NOT_FOUND")
            
        config = await self.gov_repo.get_config()
        empresa = config.SYS_Nombre_Empresa or "Nuestra Empresa"

        # 2. Configuración del Documento
        doc = Document()
        style = doc.styles['Normal']
        style.font.name = 'Arial'
        style.font.size = Pt(11)

        # --- ENCABEZADO ---
        fecha_str = datetime.now().strftime("%d/%m/%Y")
        p_fecha = doc.add_paragraph(f"Guatemala, {fecha_str}")
        p_fecha.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        doc.add_paragraph() 

        # --- TÍTULO ---
        titulo = doc.add_paragraph("NOTA: ENTREGA DE EQUIPO / ACTIVO")
        titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        titulo.runs[0].bold = True
        titulo.runs[0].font.size = Pt(14)
        titulo.runs[0].font.underline = True
        doc.add_paragraph() 

        # --- INTRODUCCIÓN ---
        p_intro = doc.add_paragraph()
        p_intro.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p_intro.add_run("El siguiente documento se extiende como respaldo para la entrega de dispositivos propiedad de ")
        r_empresa = p_intro.add_run(f"{empresa}")
        r_empresa.bold = True
        r_empresa.font.color.rgb = RGBColor(0, 51, 102)
        
        p_intro.add_run(f", asignados al colaborador ")
        r_colab = p_intro.add_run(f"{movimiento.persona.PER_Primer_Nombre} {movimiento.persona.PER_Primer_Apellido}")
        r_colab.bold = True
        
        p_intro.add_run(", detallados a continuación:")
        doc.add_paragraph() 

        # --- TABLA ---
        table = doc.add_table(rows=1, cols=4)
        table.style = 'Table Grid'
        table.autofit = True
        
        hdr_cells = table.rows[0].cells
        headers = ['CÓDIGO', 'TIPO / MARCA', 'MODELO', 'SERIE']
        for i, text in enumerate(headers):
            p = hdr_cells[i].paragraphs[0]
            p.add_run(text).bold = True
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        row_cells = table.add_row().cells
        
        tipo = movimiento.activo.tipo_activo.TAC_Nombre if movimiento.activo.tipo_activo else "N/A"
        marca = movimiento.activo.modelo.marca.MAR_Nombre if movimiento.activo.modelo and movimiento.activo.modelo.marca else "N/A"
        modelo = movimiento.activo.modelo.MOD_Nombre if movimiento.activo.modelo else "N/A"

        datos = [
            movimiento.activo.ACT_Codigo_Interno,
            f"{tipo} - {marca}",
            modelo,
            movimiento.activo.ACT_Serie_Fabricante
        ]

        for i, dato in enumerate(datos):
            p = row_cells[i].paragraphs[0]
            p.add_run(str(dato)).font.size = Pt(10)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        doc.add_paragraph() 

        # --- LEGAL ---
        p_legal = doc.add_paragraph()
        p_legal.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p_legal.add_run("El usuario se compromete a cuidar el equipo listado. Motivo: ")
        p_legal.add_run(f"{movimiento.MOV_Observacion or 'Asignación Regular'}").italic = True
        
        doc.add_paragraph("\n\n\n\n") 

        # --- FIRMAS ---
        firma_table = doc.add_table(rows=1, cols=2)
        firma_table.autofit = True
        
        c1 = firma_table.rows[0].cells[0]
        c1.paragraphs[0].add_run("__________________________\nRECIBE CONFORME\n").bold = True
        c1.paragraphs[0].add_run(f"{movimiento.persona.PER_Primer_Nombre} {movimiento.persona.PER_Primer_Apellido}\nColaborador")
        c1.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

        c2 = firma_table.rows[0].cells[1]
        c2.paragraphs[0].add_run("__________________________\nENTREGA / AUTORIZA\n").bold = True
        c2.paragraphs[0].add_run(f"Departamento de IT\n{empresa}")
        c2.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer

    # =================================================================
    # MÉTODO 2: ACTA MÚLTIPLE (LOTE)
    # =================================================================
    async def generar_acta_multiple(self, movimiento_ids: List[uuid.UUID]) -> BytesIO:
        """
        Genera un Acta de Entrega UNIFICADA para múltiples activos.
        """
        # 1. Obtener Datos
        movimientos = []
        for mov_id in movimiento_ids:
            mov = await self.trace_repo.get_by_id_full(mov_id)
            if not mov:
                raise HTTPException(status_code=404, detail=f"MOVEMENT_NOT_FOUND: {mov_id}")
            movimientos.append(mov)

        if not movimientos:
            raise HTTPException(status_code=400, detail="NO_MOVEMENTS_PROVIDED")

        # Validar misma persona
        persona_base = movimientos[0].persona
        for mov in movimientos:
            if mov.PER_Persona != persona_base.PER_Persona:
                raise HTTPException(status_code=400, detail="CANNOT_MIX_DIFFERENT_PEOPLE_IN_SAME_DOCUMENT")

        config = await self.gov_repo.get_config()
        empresa = config.SYS_Nombre_Empresa or "Nuestra Empresa"

        # 2. Documento
        doc = Document()
        style = doc.styles['Normal']
        style.font.name = 'Arial'
        style.font.size = Pt(11)

        # Encabezado
        fecha_str = datetime.now().strftime("%d/%m/%Y")
        p_fecha = doc.add_paragraph(f"Guatemala, {fecha_str}")
        p_fecha.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        doc.add_paragraph() 

        titulo = doc.add_paragraph("NOTA: ENTREGA DE EQUIPOS (LOTE)")
        titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        titulo.runs[0].bold = True
        titulo.runs[0].font.size = Pt(14)
        titulo.runs[0].font.underline = True
        doc.add_paragraph() 

        # Intro
        p_intro = doc.add_paragraph()
        p_intro.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p_intro.add_run("El siguiente documento respalda la entrega de múltiples dispositivos de ")
        r_empresa = p_intro.add_run(f"{empresa}")
        r_empresa.bold = True
        r_empresa.font.color.rgb = RGBColor(0, 51, 102)
        p_intro.add_run(f", asignados a ")
        r_colab = p_intro.add_run(f"{persona_base.PER_Primer_Nombre} {persona_base.PER_Primer_Apellido}")
        r_colab.bold = True
        p_intro.add_run(":")
        doc.add_paragraph() 

        # Tabla Dinámica
        table = doc.add_table(rows=1, cols=4)
        table.style = 'Table Grid'
        table.autofit = True
        
        headers = ['CÓDIGO', 'TIPO / MARCA', 'MODELO', 'SERIE']
        for i, text in enumerate(headers):
            p = table.rows[0].cells[i].paragraphs[0]
            p.add_run(text).bold = True
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        for mov in movimientos:
            row_cells = table.add_row().cells
            
            tipo = mov.activo.tipo_activo.TAC_Nombre if mov.activo.tipo_activo else ""
            marca = mov.activo.modelo.marca.MAR_Nombre if mov.activo.modelo and mov.activo.modelo.marca else ""
            modelo = mov.activo.modelo.MOD_Nombre if mov.activo.modelo else ""

            datos = [
                mov.activo.ACT_Codigo_Interno,
                f"{tipo} - {marca}",
                modelo,
                mov.activo.ACT_Serie_Fabricante
            ]

            for i, dato in enumerate(datos):
                p = row_cells[i].paragraphs[0]
                p.add_run(str(dato)).font.size = Pt(10)
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        doc.add_paragraph() 
        
        # Legal y Firmas
        p_legal = doc.add_paragraph("El usuario se hace responsable del cuidado y custodia de los activos listados anteriormente.")
        doc.add_paragraph("\n\n\n\n") 

        firma_table = doc.add_table(rows=1, cols=2)
        firma_table.autofit = True
        
        c1 = firma_table.rows[0].cells[0]
        c1.paragraphs[0].add_run("__________________________\nRECIBE CONFORME\n").bold = True
        c1.paragraphs[0].add_run(f"{persona_base.PER_Primer_Nombre} {persona_base.PER_Primer_Apellido}\nColaborador")
        c1.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

        c2 = firma_table.rows[0].cells[1]
        c2.paragraphs[0].add_run("__________________________\nENTREGA / AUTORIZA\n").bold = True
        c2.paragraphs[0].add_run(f"Departamento de IT\n{empresa}")
        c2.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer