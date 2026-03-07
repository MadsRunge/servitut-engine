import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service

st.set_page_config(page_title="Inspicér sider", layout="wide")
st.title("Inspicér OCR-sider")
st.caption("Sidebillede (original PDF) + OCR-tekst (fra ocr.pdf) side om side")

cases = case_service.list_cases()
if not cases:
    st.warning("Ingen cases.")
    st.stop()

case_options = {f"{c.name} ({c.case_id})": c.case_id for c in cases}
selected_label = st.selectbox("Vælg case", list(case_options.keys()))
case_id = case_options[selected_label]

docs = storage_service.list_documents(case_id)
ocr_docs = [d for d in docs if d.parse_status == "ocr_done"]
if not ocr_docs:
    st.info("Ingen dokumenter med OCR endnu. Kør OCR under trin 3.")
    st.stop()

doc_options = {f"{d.filename} ({d.document_id})": d.document_id for d in ocr_docs}
selected_doc_label = st.selectbox("Vælg dokument", list(doc_options.keys()))
doc_id = doc_options[selected_doc_label]

doc = storage_service.load_document(case_id, doc_id)
pages = storage_service.load_ocr_pages(case_id, doc_id)
if not pages:
    st.warning("Ingen OCR-data fundet.")
    st.stop()

st.info(f"{len(pages)} sider")

# Indlæs original PDF til billedrendering
pdf_path = storage_service.get_document_pdf_path(case_id, doc_id)


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
    conf_color = "green" if page.confidence >= 0.7 else "orange" if page.confidence > 0.0 else "gray"
    with st.expander(
        f"Side {page.page_number} — :{conf_color}[conf={page.confidence:.2f}] — {len(page.text)} tegn"
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
                    label="",
                    value=page.text,
                    height=400,
                    key=f"ocr_text_{doc_id}_{page.page_number}",
                )
            else:
                st.warning("Ingen tekst udtrukket — blank eller ulæselig side.")
