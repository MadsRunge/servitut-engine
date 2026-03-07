import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service
from app.services.chunking_service import chunk_pages
from app.services.ocr_service import process_document

st.set_page_config(page_title="Kør OCR", layout="wide")
st.title("Kør OCR på dokumenter")
st.caption("PDF → sidebilleder (pymupdf) → tekst (Claude Vision) → chunks")

cases = case_service.list_cases()
if not cases:
    st.warning("Ingen cases. Opret en case først.")
    st.stop()

case_options = {f"{c.name} ({c.case_id})": c.case_id for c in cases}
selected_label = st.selectbox("Vælg case", list(case_options.keys()))
case_id = case_options[selected_label]

docs = storage_service.list_documents(case_id)
if not docs:
    st.warning("Ingen dokumenter. Upload dokumenter først.")
    st.stop()

for doc in docs:
    status_badge = {
        "pending": "⏳ Afventer",
        "ocr_done": "✅ OCR færdig",
        "error": "❌ Fejl",
    }.get(doc.parse_status, doc.parse_status)

    with st.expander(f"**{doc.filename}** — {status_badge}"):
        col1, col2 = st.columns([3, 1])
        col1.caption(f"ID: `{doc.document_id}` | Sider: {doc.page_count}")

        if col2.button("Kør OCR", key=f"ocr_{doc.document_id}", type="primary"):
            pdf_path = Path(doc.file_path)
            images_dir = storage_service.get_page_images_dir(case_id, doc.document_id)

            with st.spinner(f"OCR kører på {doc.filename}..."):
                try:
                    pages = process_document(pdf_path, doc.document_id, case_id, images_dir)
                    storage_service.save_ocr_pages(case_id, doc.document_id, pages)

                    doc.pages = pages
                    doc.page_count = len(pages)
                    doc.parse_status = "ocr_done"
                    storage_service.save_document(doc)

                    chunks = chunk_pages(pages, doc.document_id, case_id)
                    storage_service.save_chunks(case_id, doc.document_id, chunks)

                    st.success(f"OCR færdig: {len(pages)} sider, {len(chunks)} chunks")
                    st.rerun()
                except Exception as e:
                    doc.parse_status = "error"
                    storage_service.save_document(doc)
                    st.error(f"Fejl: {e}")

        if doc.parse_status == "ocr_done":
            pages = storage_service.load_ocr_pages(case_id, doc.document_id)
            for page in pages:
                conf_color = "green" if page.confidence >= 0.8 else "orange"
                st.markdown(
                    f"**Side {page.page_number}** — "
                    f":{conf_color}[conf={page.confidence:.1f}] — "
                    f"{len(page.text)} tegn"
                )
