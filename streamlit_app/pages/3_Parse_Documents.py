import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service
from app.services.chunking_service import chunk_pages
from app.services.pdf_service import parse_pdf

st.set_page_config(page_title="Parse dokumenter", layout="wide")
st.title("Parse PDF-dokumenter")

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
    with st.expander(f"**{doc.filename}** — `{doc.parse_status}`"):
        if st.button(f"Parse '{doc.filename}'", key=f"parse_{doc.document_id}"):
            pdf_path = Path(doc.file_path)
            with st.spinner("Parser..."):
                try:
                    pages = parse_pdf(pdf_path)
                    doc.pages = pages
                    doc.page_count = len(pages)
                    doc.parse_status = "parsed"
                    storage_service.save_document(doc)
                    chunks = chunk_pages(pages, doc.document_id, case_id)
                    storage_service.save_chunks(case_id, doc.document_id, chunks)
                    st.success(f"Parsed {len(pages)} sider, {len(chunks)} chunks")
                except Exception as e:
                    st.error(f"Fejl: {e}")
                    doc.parse_status = "error"
                    storage_service.save_document(doc)

        if doc.pages:
            for page in doc.pages:
                badge = "✅" if page.extraction_method == "pdfplumber" else "⚠️ OCR-kandidat"
                st.markdown(
                    f"**Side {page.page_number}** {badge} (conf={page.confidence:.1f})"
                )
                st.text_area(
                    f"Tekst side {page.page_number}",
                    page.text[:1000] + ("..." if len(page.text) > 1000 else ""),
                    height=100,
                    key=f"page_{doc.document_id}_{page.page_number}",
                )
