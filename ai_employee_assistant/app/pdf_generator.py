import os
import io
import sys
import base64
from datetime import datetime
from zoneinfo import ZoneInfo
from config import settings
from html import escape
sys.path.append("/Users/junaid/Library/Python/3.9/lib/python/site-packages")

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

def generate_pdf_report(title: str, summary_text: str, chart_base64: str = None, dataset_name: str = "Financial Ledger") -> bytes:
    """Create a PDF audit report with findings and an optional chart."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    story = []
    styles = getSampleStyleSheet()

    PRIMARY = colors.HexColor('#0f172a')   # Obsidian
    ACCENT_INDIGO = colors.HexColor('#6366f1')
    ACCENT_CYAN = colors.HexColor('#06b6d4')
    TEXT_DARK = colors.HexColor('#1e293b')
    TEXT_MUTED = colors.HexColor('#64748b')

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        textColor=PRIMARY,
        alignment=TA_LEFT
    )
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=14,
        textColor=ACCENT_INDIGO,
        alignment=TA_LEFT
    )
    body_style = ParagraphStyle(
        'BodyTextCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=15,
        textColor=TEXT_DARK
    )
    section_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=ACCENT_CYAN,
        spaceBefore=12,
        spaceAfter=6
    )

    story.append(Paragraph("AI EMPLOYEE ASSISTANT • EXECUTIVE AUDIT BRIEFING", subtitle_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(escape(title.upper()), title_style))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=2, color=ACCENT_INDIGO, spaceAfter=15))

    meta_data = [
        [Paragraph("<b>Target Dataset:</b>", body_style), Paragraph(escape(dataset_name), body_style),
         Paragraph("<b>Review Status:</b>", body_style), Paragraph("Automated analysis — review required", body_style)],
        [Paragraph("<b>Report Date:</b>", body_style), Paragraph(datetime.now(ZoneInfo(settings.MCP_LOCAL_TIMEZONE)).strftime("%B %d, %Y"), body_style),
         Paragraph("<b>Classification:</b>", body_style), Paragraph("RESTRICTED / C-SUITE ONLY", body_style)]
    ]
    t_meta = Table(meta_data, colWidths=[100, 160, 100, 160])
    t_meta.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE')
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 15))

    story.append(Paragraph("1. Executive Summary & Key Findings", section_style))
    clean_lines = [line.strip().replace('**', '').replace('*', '') for line in summary_text.split('\n') if line.strip()]
    for line in clean_lines[:10]:
        story.append(Paragraph(f"• {escape(line)}", body_style))
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 10))

    if chart_base64:
        story.append(Paragraph("2. Financial Trend & Distribution Visualization", section_style))
        img_data = base64.b64decode(chart_base64)
        img_stream = io.BytesIO(img_data)
        img = Image(img_stream, width=500, height=240)
        story.append(img)
        story.append(Spacer(1, 15))

    story.append(Paragraph("3. Review Scope", section_style))
    sign_data = [
        [Paragraph("<b>Prepared by:</b> AI Employee Assistant", body_style),
         Paragraph("<b>Assurance:</b> No independent audit opinion", body_style)],
        [Paragraph("<b>Scope:</b> Supplied data and selected calculations", body_style),
         Paragraph("<b>Review:</b> Validate source data and accounting treatment", body_style)]
    ]
    t_sign = Table(sign_data, colWidths=[260, 260])
    t_sign.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f1f5f9')),
        ('PADDING', (0,0), (-1,-1), 8),
        ('BOX', (0,0), (-1,-1), 1, ACCENT_INDIGO),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE')
    ]))
    story.append(t_sign)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
