import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.db.database import get_session_ctx
from app.services import case_service, storage_service
from streamlit_app.ui import (
    confidence_band,
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_section,
    select_case,
    select_document,
    setup_page,
)

setup_page(
    "Inspicér sider",
    "Gennemgå OCR-resultatet side for side. Brug denne visning til at spotte blanke eller svage sider før ekstraktion.",
    step="pages",
)

case = select_case()
render_case_banner(case)
render_case_stats(case.case_id)

with get_session_ctx() as session:
    docs = storage_service.list_documents(session, case.case_id)
ocr_docs = [d for d in docs if d.parse_status == "ocr_done"]
if not ocr_docs:
    render_empty_state("Ingen OCR-klare dokumenter", "Kør OCR i trin 3, før sider kan inspiceres.")
    st.stop()

render_section("Dokumentvisning", "Vælg et OCR-behandlet dokument og gennemgå tekstkvaliteten.")
doc = select_document(case.case_id, ocr_docs)
with get_session_ctx() as session:
    pages = storage_service.load_ocr_pages(session, case.case_id, doc.document_id)
if not pages:
    render_empty_state("Ingen OCR-data", "Dokumentet har ingen gemte OCR-sider endnu.")
    st.stop()

good_pages = sum(1 for page in pages if page.confidence >= 0.7)
low_pages = sum(1 for page in pages if 0.0 < page.confidence < 0.7)
blank_pages = sum(1 for page in pages if page.confidence == 0.0)
st.caption(f"{doc.filename} · {len(pages)} sider")
col1, col2, col3 = st.columns(3)
col1.metric("Gode sider", str(good_pages))
col2.metric("Lav confidence", str(low_pages))
col3.metric("Blanke sider", str(blank_pages))

filter_val = st.radio(
    "Filtrer sider",
    ["Alle", "God (≥0.7)", "Lav confidence", "Blanke"],
    horizontal=True,
    label_visibility="collapsed",
)
pages = {
    "Alle": pages,
    "God (≥0.7)": [p for p in pages if p.confidence >= 0.7],
    "Lav confidence": [p for p in pages if 0.0 < p.confidence < 0.7],
    "Blanke": [p for p in pages if p.confidence == 0.0],
}[filter_val]
if not pages:
    st.info(f"Ingen sider matcher filteret '{filter_val}'.")
    st.stop()

# Indlæs original PDF til billedrendering
pdf_path = storage_service.get_document_pdf_path(case.case_id, doc.document_id)


def render_page_image(pdf_path: Path, page_number: int) -> bytes | None:
    """Render en PDF-side til PNG-bytes med pymupdf."""
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        page = doc[page_number - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_bytes = pix.tobytes("png")
        doc.close()
        return img_bytes
    except Exception:
        return None


for page in pages:
    conf_label, conf_color = confidence_band(page.confidence)
    with st.expander(
        f"Side {page.page_number} · {conf_label} · conf={page.confidence:.2f} · {len(page.text)} tegn"
    ):
        col_img, col_txt = st.columns(2)

        with col_img:
            st.caption("Originalt sidebillede")
            if pdf_path.exists():
                img = render_page_image(pdf_path, page.page_number)
                if img:
                    st.image(img)
                else:
                    st.info("Kunne ikke rendere billede.")
            else:
                st.info("Original PDF ikke fundet.")

        with col_txt:
            st.caption("OCR-tekst (ocrmypdf + pdfplumber)")
            if page.text:
                st.text_area(
                    label=f"OCR-tekst for side {page.page_number}",
                    label_visibility="collapsed",
                    value=page.text,
                    height=400,
                    key=f"ocr_text_{doc.document_id}_{page.page_number}",
                )
            else:
                st.warning("Ingen tekst udtrukket — blank eller ulæselig side.")
