import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service
from app.services.chunking_service import chunk_pages
from app.services.ocr_service import process_document
from streamlit_app.ui import (
    parse_status_label,
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_section,
    select_case,
    setup_page,
)

setup_page(
    "Kør OCR",
    "Behandl uploadede PDF’er gennem OCR-pipelinen. Resultatet bliver side-tekst, OCR-PDF og chunks klar til udtræk.",
    step="ocr",
)

case = select_case()
render_case_banner(case)
render_case_stats(case.case_id)

render_section("OCR-kø", "Kør dokumenter enkeltvis og følg, hvilke der er klar til næste trin.")
docs = storage_service.list_documents(case.case_id)
if not docs:
    render_empty_state("Ingen dokumenter", "Upload dokumenter før du starter OCR.")
    st.stop()

for doc in docs:
    with st.expander(f"{doc.filename} · {parse_status_label(doc.parse_status)}", expanded=doc.parse_status != "ocr_done"):
        col1, col2, col3 = st.columns([3, 1, 1])
        col1.caption(f"Dokument-id: `{doc.document_id}`")
        col2.metric("Sider", str(doc.page_count))
        col3.metric("Status", parse_status_label(doc.parse_status))

        if st.button("Kør OCR nu", key=f"ocr_{doc.document_id}", type="primary", use_container_width=True):
            pdf_path = Path(doc.file_path)
            ocr_pdf_path = storage_service.get_ocr_pdf_path(case.case_id, doc.document_id)

            with st.spinner(f"OCR kører på {doc.filename} (ocrmypdf)..."):
                try:
                    pages = process_document(pdf_path, doc.document_id, case.case_id, ocr_pdf_path)
                    storage_service.save_ocr_pages(case.case_id, doc.document_id, pages)

                    doc.pages = pages
                    doc.page_count = len(pages)
                    doc.parse_status = "ocr_done"
                    storage_service.save_document(doc)

                    chunks = chunk_pages(pages, doc.document_id, case.case_id)
                    storage_service.save_chunks(case.case_id, doc.document_id, chunks)

                    st.success(f"OCR færdig: {len(pages)} sider, {len(chunks)} chunks")
                    st.rerun()
                except Exception as e:
                    doc.parse_status = "error"
                    storage_service.save_document(doc)
                    st.error(f"Fejl: {e}")

        if doc.parse_status == "ocr_done":
            pages = storage_service.load_ocr_pages(case.case_id, doc.document_id)
            blank = sum(1 for p in pages if p.confidence == 0.0)
            low = sum(1 for p in pages if 0.0 < p.confidence < 0.4)
            ok = len(pages) - blank - low
            st.markdown(
                f"**{len(pages)} sider** — "
                f":green[{ok} ok] · "
                f":orange[{low} lav conf] · "
                f":gray[{blank} blanke]"
            )
