import sys
from copy import deepcopy
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


def _render_ocr_summary(placeholders: list, total_docs: int, done_docs: int) -> None:
    remaining_docs = max(total_docs - done_docs, 0)
    placeholders[0].metric("Dokumenter i alt", str(total_docs))
    placeholders[1].metric("OCR færdige", str(done_docs))
    placeholders[2].metric("Klar til kørsel", str(remaining_docs))


def _batch_state_for_document(doc: Document) -> tuple[str, str]:
    if doc.parse_status == "ocr_done":
        return "Færdig", "OCR og chunks gemt"
    if doc.parse_status == "processing":
        return "Kører", "OCRmyPDF og tekstudtræk i gang"
    if doc.parse_status == "error":
        return "Fejl", "Kræver ny kørsel"
    return "I kø", "Afventer behandling"


def _batch_state_key(case_id: str) -> str:
    return f"ocr_batch_state_{case_id}"


def _get_batch_state(case_id: str) -> dict | None:
    state = st.session_state.get(_batch_state_key(case_id))
    if not isinstance(state, dict):
        return None
    return state


def _set_batch_state(case_id: str, state: dict) -> None:
    st.session_state[_batch_state_key(case_id)] = state


def _clear_batch_state(case_id: str) -> None:
    st.session_state.pop(_batch_state_key(case_id), None)


def _build_status_snapshot(docs: list[Document]) -> dict[str, tuple[str, str]]:
    return {doc.filename: _batch_state_for_document(doc) for doc in docs}


def _next_batch_document(case_id: str, pending_ids: list[str]) -> Document | None:
    for doc_id in pending_ids:
        doc = storage_service.load_document(case_id, doc_id, include_pages=False)
        if doc and doc.parse_status != "ocr_done":
            return doc
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
batch_state = _get_batch_state(case.case_id)
batch_running = batch_state is not None

summary_col1, summary_col2, summary_col3 = st.columns(3)
summary_placeholders = [summary_col1.empty(), summary_col2.empty(), summary_col3.empty()]
_render_ocr_summary(summary_placeholders, len(docs), done_count)

if batch_state:
    pending_ids = list(batch_state.get("pending_doc_ids", []))
    failures = list(batch_state.get("failures", []))
    next_doc = _next_batch_document(case.case_id, pending_ids)

    progress = st.progress(
        done_count / len(docs) if docs else 1.0,
        text=f"OCR færdig for {done_count}/{len(docs)} dokumenter",
    )
    snapshot_ph = st.empty()
    statuses = _build_status_snapshot(docs)
    if next_doc:
        statuses[next_doc.filename] = ("Kører", "OCRmyPDF og tekstudtræk i gang")
    render_batch_snapshot(snapshot_ph, statuses)

    status_col1, status_col2 = st.columns([3, 2])
    if next_doc:
        status_col1.info(
            f"Batch-OCR aktiv. Behandler nu `{next_doc.filename}` "
            f"({len(pending_ids)} dokumenter tilbage i kø)."
        )
    else:
        status_col1.info("Batch-OCR afslutter og synkroniserer status.")
    if status_col2.button("Stop batch-OCR", type="secondary", width="stretch"):
        _clear_batch_state(case.case_id)
        st.session_state["ocr_batch_feedback"] = (
            "warning",
            "Batch-OCR blev stoppet manuelt.",
        )
        st.rerun()

    if not next_doc:
        if failures:
            st.session_state["ocr_batch_feedback"] = (
                "warning",
                f"Batch-OCR afsluttet med {len(failures)} fejl.",
            )
        else:
            st.session_state["ocr_batch_feedback"] = (
                "success",
                f"Batch-OCR færdig. {done_count}/{len(docs)} dokumenter har nu OCR-status `ocr_done`.",
            )
        _clear_batch_state(case.case_id)
        st.rerun()

    with st.spinner(f"Kører OCR på {next_doc.filename}..."):
        ok, message = run_ocr_for_document(case.case_id, next_doc)

    updated_state = deepcopy(batch_state)
    updated_state["pending_doc_ids"] = [doc_id for doc_id in pending_ids if doc_id != next_doc.document_id]
    if not ok:
        failures.append(f"{next_doc.filename}: {message}")
    updated_state["failures"] = failures
    _set_batch_state(case.case_id, updated_state)
    st.rerun()

if docs_to_process:
    actions_col1, actions_col2 = st.columns([2, 3])
    if actions_col1.button(
        "Kør OCR på alle ikke-færdige",
        type="primary",
        width="stretch",
        disabled=batch_running,
    ):
        _set_batch_state(
            case.case_id,
            {
                "pending_doc_ids": [doc.document_id for doc in docs_to_process],
                "failures": [],
            },
        )
        st.rerun()
    if batch_running:
        actions_col2.caption(
            "Batch-kørsel er aktiv. Siden rerender mellem dokumenter, så status og tællere følger den faktiske state på disken."
        )
    else:
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
        width="content",
        disabled=batch_running,
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

        if st.button(
            "Kør OCR nu",
            key=f"ocr_{doc.document_id}",
            type="primary",
            width="stretch",
            disabled=batch_running,
        ):
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
