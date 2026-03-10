import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service
from app.services.chunking_service import chunk_pages
from app.services.document_classifier import classify_document
from app.models.document import Document
from app.services.ocr_service import process_document, summarize_pages
from streamlit_app.ui import (
    parse_status_label,
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_section,
    select_case,
    setup_page,
)


def _preserve_known_document_type(document_type: str) -> str | None:
    if document_type in {"akt", "tinglysningsattest"}:
        return document_type
    return None


def render_batch_snapshot(snapshot_ph, statuses: dict[str, tuple[str, str]]) -> None:
    lines = ["**Batch-status**"]
    for filename, (state, detail) in statuses.items():
        lines.append(f"- `{filename}` · {state} · {detail}")
    snapshot_ph.markdown("\n".join(lines))


def run_ocr_for_document(case_id: str, doc: Document) -> tuple[bool, str]:
    pdf_path = Path(doc.file_path)
    ocr_pdf_path = storage_service.get_ocr_pdf_path(case_id, doc.document_id)

    try:
        doc.parse_status = "processing"
        storage_service.save_document(doc)

        pages = process_document(pdf_path, doc.document_id, case_id, ocr_pdf_path)
        storage_service.save_ocr_pages(case_id, doc.document_id, pages)

        blank, low, _ = summarize_pages(pages)
        chunks = chunk_pages(pages, doc.document_id, case_id)

        doc.pages = pages
        doc.page_count = len(pages)
        doc.chunk_count = len(chunks)
        doc.ocr_blank_pages = blank
        doc.ocr_low_conf_pages = low
        doc.document_type = classify_document(
            doc.filename,
            pages=pages,
            requested_type=_preserve_known_document_type(doc.document_type),
        )
        doc.parse_status = "ocr_done"
        storage_service.save_document(doc)

        storage_service.save_chunks(case_id, doc.document_id, chunks)
        return True, f"{len(pages)} sider, {len(chunks)} chunks"
    except Exception as exc:
        doc.parse_status = "error"
        storage_service.save_document(doc)
        return False, str(exc)


setup_page(
    "Kør OCR",
    "Behandl uploadede PDF’er gennem OCR-pipelinen. Resultatet bliver side-tekst, OCR-PDF og chunks klar til udtræk.",
    step="ocr",
)

batch_feedback = st.session_state.pop("ocr_batch_feedback", None)
if batch_feedback:
    level, message = batch_feedback
    getattr(st, level)(message)

case = select_case()
render_case_banner(case)
render_case_stats(case.case_id)

render_section("OCR-kø", "Kør dokumenter enkeltvis og følg, hvilke der er klar til næste trin.")
docs = storage_service.list_documents(case.case_id)
if not docs:
    render_empty_state("Ingen dokumenter", "Upload dokumenter før du starter OCR.")
    st.stop()

docs_to_process = [doc for doc in docs if doc.parse_status != "ocr_done"]
done_count = len(docs) - len(docs_to_process)

summary_col1, summary_col2, summary_col3 = st.columns(3)
summary_col1.metric("Dokumenter i alt", str(len(docs)))
summary_col2.metric("OCR færdige", str(done_count))
summary_col3.metric("Klar til kørsel", str(len(docs_to_process)))

if docs_to_process:
    actions_col1, actions_col2 = st.columns([2, 3])
    if actions_col1.button("Kør OCR på alle ikke-færdige", type="primary", use_container_width=True):
        progress = st.progress(0.0, text="Starter batch-OCR...")
        current_doc_ph = st.empty()
        snapshot_ph = st.empty()
        completed = 0
        failures: list[str] = []
        statuses = {
            doc.filename: (
                "I kø",
                "Afventer behandling",
            )
            for doc in docs_to_process
        }
        render_batch_snapshot(snapshot_ph, statuses)

        for index, doc in enumerate(docs_to_process, start=1):
            progress.progress(
                (index - 1) / len(docs_to_process),
                text=f"Behandler {index}/{len(docs_to_process)}: {doc.filename}",
            )
            statuses[doc.filename] = ("Kører", "OCRmyPDF og tekstudtræk i gang")
            current_doc_ph.info(f"Kører OCR på `{doc.filename}`")
            render_batch_snapshot(snapshot_ph, statuses)

            ok, message = run_ocr_for_document(case.case_id, doc)
            completed += 1
            if ok:
                statuses[doc.filename] = ("Færdig", message)
            else:
                failures.append(f"{doc.filename}: {message}")
                statuses[doc.filename] = ("Fejl", message)
            render_batch_snapshot(snapshot_ph, statuses)

            progress.progress(
                completed / len(docs_to_process),
                text=f"Færdig {completed}/{len(docs_to_process)} dokumenter",
            )

        if failures:
            st.session_state["ocr_batch_feedback"] = (
                "warning",
                f"Batch-OCR afsluttet med {len(failures)} fejl.",
            )
        else:
            st.session_state["ocr_batch_feedback"] = (
                "success",
                f"Batch-OCR færdig for {completed} dokumenter.",
            )
        current_doc_ph.empty()
        st.rerun()
    actions_col2.caption(
        "Batch-kørsel tager alle dokumenter, der endnu ikke har status `OCR færdig`, og behandler dem sekventielt."
    )
else:
    st.caption("Alle dokumenter er allerede OCR-behandlet.")

failed_docs = [doc for doc in docs if doc.parse_status == "error"]
if failed_docs:
    st.divider()
    if st.button(
        f"🔁 Kør OCR igen på {len(failed_docs)} fejlede dokument(er)",
        type="secondary",
        use_container_width=False,
    ):
        for doc in failed_docs:
            with st.spinner(f"Kører OCR igen: {doc.filename}…"):
                ok, message = run_ocr_for_document(case.case_id, doc)
                if ok:
                    st.success(f"{doc.filename}: {message}")
                else:
                    st.error(f"{doc.filename}: {message}")
        st.rerun()

for doc in docs:
    with st.expander(f"{doc.filename} · {parse_status_label(doc.parse_status)}", expanded=doc.parse_status != "ocr_done"):
        col1, col2, col3 = st.columns([3, 1, 1])
        col1.caption(f"Dokument-id: `{doc.document_id}`")
        col2.metric("Sider", str(doc.page_count))
        col3.metric("Status", parse_status_label(doc.parse_status))

        if st.button("Kør OCR nu", key=f"ocr_{doc.document_id}", type="primary", use_container_width=True):
            with st.spinner(f"OCR kører på {doc.filename} (ocrmypdf)..."):
                ok, message = run_ocr_for_document(case.case_id, doc)
                if ok:
                    st.success(f"OCR færdig: {message}")
                    st.rerun()
                st.error(f"Fejl: {message}")

        if doc.parse_status == "ocr_done":
            blank = doc.ocr_blank_pages
            low = doc.ocr_low_conf_pages
            ok = doc.page_count - blank - low
            st.markdown(
                f"**{doc.page_count} sider** — "
                f":green[{ok} ok] · "
                f":orange[{low} lav conf] · "
                f":gray[{blank} blanke]"
            )
