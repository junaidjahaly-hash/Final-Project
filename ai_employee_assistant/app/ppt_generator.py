import os
import io
import sys
import base64
sys.path.append("/Users/junaid/Library/Python/3.9/lib/python/site-packages")

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

def create_executive_deck(title: str, summary_text: str, chart_base64: str = None, stats_dict: dict = None) -> bytes:
    """Create a PowerPoint deck with a summary, metrics, chart, and action plan."""
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    BG_COLOR = RGBColor(15, 23, 42)      # #0f172a
    CARD_BG = RGBColor(30, 41, 59)      # #1e293b
    ACCENT_INDIGO = RGBColor(99, 102, 241) # #6366f1
    ACCENT_CYAN = RGBColor(6, 182, 212)  # #06b6d4
    TEXT_LIGHT = RGBColor(248, 250, 252) # #f8fafc
    TEXT_MUTED = RGBColor(148, 163, 184) # #94a3b8

    blank_layout = prs.slide_layouts[6]

    # Slide 1: title slide
    slide1 = prs.slides.add_slide(blank_layout)
    bg1 = slide1.shapes.add_shape(1, 0, 0, Inches(13.333), Inches(7.5)) # Rect
    bg1.fill.solid(); bg1.fill.fore_color.rgb = BG_COLOR
    bg1.line.fill.background()

    txBox = slide1.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(11.333), Inches(3.5))
    tf = txBox.text_frame
    tf.word_wrap = True
    
    p = tf.paragraphs[0]
    p.text = "EXECUTIVE BRIEFING"
    p.font.size = Pt(16); p.font.bold = True; p.font.color.rgb = ACCENT_CYAN
    p.alignment = PP_ALIGN.LEFT

    p2 = tf.add_paragraph()
    p2.text = title.upper()
    p2.font.size = Pt(36); p2.font.bold = True; p2.font.color.rgb = TEXT_LIGHT

    p3 = tf.add_paragraph()
    p3.text = "AI Employee Assistant • Enterprise Data & Governance Audit Engine"
    p3.font.size = Pt(14); p3.font.color.rgb = TEXT_MUTED

    # Slide 2: executive summary & metric cards
    slide2 = prs.slides.add_slide(blank_layout)
    bg2 = slide2.shapes.add_shape(1, 0, 0, Inches(13.333), Inches(7.5))
    bg2.fill.solid(); bg2.fill.fore_color.rgb = BG_COLOR; bg2.line.fill.background()

    t_box = slide2.shapes.add_textbox(Inches(0.8), Inches(0.5), Inches(11.7), Inches(1.0))
    tf2 = t_box.text_frame; tf2.word_wrap = True
    p = tf2.paragraphs[0]
    p.text = "EXECUTIVE SUMMARY & KEY FINDINGS"
    p.font.size = Pt(24); p.font.bold = True; p.font.color.rgb = ACCENT_INDIGO

    s_box = slide2.shapes.add_textbox(Inches(0.8), Inches(1.5), Inches(11.7), Inches(5.2))
    tf_s = s_box.text_frame; tf_s.word_wrap = True
    
    clean_lines = [line.strip() for line in summary_text.split('\n') if line.strip()]
    for line in clean_lines[:8]:
        p = tf_s.add_paragraph()
        p.text = line.replace('**', '').replace('*', '')
        p.font.size = Pt(16); p.font.color.rgb = TEXT_LIGHT
        p.space_after = Pt(12)

    # Slide 3: visualization & chart
    slide3 = prs.slides.add_slide(blank_layout)
    bg3 = slide3.shapes.add_shape(1, 0, 0, Inches(13.333), Inches(7.5))
    bg3.fill.solid(); bg3.fill.fore_color.rgb = BG_COLOR; bg3.line.fill.background()

    t_box3 = slide3.shapes.add_textbox(Inches(0.8), Inches(0.5), Inches(11.7), Inches(1.0))
    tf3 = t_box3.text_frame
    p = tf3.paragraphs[0]
    p.text = "DATA VISUALIZATION & BREAKDOWN"
    p.font.size = Pt(24); p.font.bold = True; p.font.color.rgb = ACCENT_INDIGO

    if chart_base64:
        img_bytes = base64.b64decode(chart_base64)
        image_stream = io.BytesIO(img_bytes)
        slide3.shapes.add_picture(image_stream, Inches(1.5), Inches(1.5), width=Inches(10.333))

    # Slide 4: strategic action plan
    slide4 = prs.slides.add_slide(blank_layout)
    bg4 = slide4.shapes.add_shape(1, 0, 0, Inches(13.333), Inches(7.5))
    bg4.fill.solid(); bg4.fill.fore_color.rgb = BG_COLOR; bg4.line.fill.background()

    t_box4 = slide4.shapes.add_textbox(Inches(0.8), Inches(0.5), Inches(11.7), Inches(1.0))
    tf4 = t_box4.text_frame
    p = tf4.paragraphs[0]
    p.text = "STRATEGIC RECOMMENDATIONS & GOVERNANCE"
    p.font.size = Pt(24); p.font.bold = True; p.font.color.rgb = ACCENT_CYAN

    recs_box = slide4.shapes.add_textbox(Inches(0.8), Inches(1.6), Inches(11.7), Inches(5.0))
    tf_r = recs_box.text_frame; tf_r.word_wrap = True
    
    recommendations = [
        "1. Reconcile high-variance ledger items with department heads prior to period close.",
        "2. Automate Benford's Law anomaly scanning on all new vendor invoices.",
        "3. Maintain SOC2 compliant audit trail exports for external consultancy verification.",
        "4. Schedule quarterly performance metric reviews using AI Employee Assistant BI Studio."
    ]
    for rec in recommendations:
        p = tf_r.add_paragraph()
        p.text = rec
        p.font.size = Pt(18); p.font.color.rgb = TEXT_LIGHT
        p.space_after = Pt(20)

    output = io.BytesIO()
    prs.save(output)
    output.seek(0)
    return output.getvalue()
