import sys
import threading
import time
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.db.database import get_session_ctx
from app.services import storage_service
from app.models.document import Document
from app.services.ocr_service import format_pipeline_result_message, run_document_pipeline
from streamlit_app.ui import (
    parse_status_label,
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_section,
    select_case,
    setup_page,
)

# Conservative estimate: ~5 seconds per page on Railway (Tesseract OCR)
SECS_PER_PAGE = 5

# Session state keys for batch threading
_BATCH_THREAD_KEY = "ocr_batch_thread"
_BATCH_RESULT_KEY = "ocr_batch_result"
_BATCH_DOC_START_KEY = "ocr_batch_doc_start"


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s"


def _single_thread_key(doc_id: str) -> str:
    return f"ocr_single_thread_{doc_id}"


def _single_result_key(doc_id: str) -> str:
    return f"ocr_single_result_{doc_id}"


def _single_start_key(doc_id: str) -> str:
    return f"ocr_single_start_{doc_id}"


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
    with get_session_ctx() as session:
        for doc_id in pending_ids:
            doc = storage_service.load_document(session, case_id, doc_id, include_pages=False)
            if doc and doc.parse_status != "ocr_done":
                return doc
    return None


def render_batch_snapshot(snapshot_ph, statuses: dict[str, tuple[str, str]]) -> None:
    lines = ["**Batch-status**"]
    for filename, (state, detail) in statuses.items():
        lines.append(f"- `{filename}` · {state} · {detail}")
    snapshot_ph.markdown("\n".join(lines))


def run_ocr_for_document(case_id: str, doc: Document) -> tuple[bool, str]:
    with get_session_ctx() as session:
        try:
            doc.parse_status = "processing"
            storage_service.save_document(session, doc)
            result = run_document_pipeline(session, case_id, doc)
            return True, format_pipeline_result_message(result)
        except Exception as exc:
            doc.parse_status = "error"
            storage_service.save_document(session, doc)
            return False, str(exc)


setup_page(
    "Kør OCR",
    "Behandl uploadede PDF'er gennem OCR-pipelinen. Resultatet bliver side-tekst, OCR-PDF og chunks klar til udtræk.",
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
with get_session_ctx() as session:
    docs = storage_service.list_documents(session, case.case_id)
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

    elapsed_total = int(time.time() - batch_state.get("start_time", time.time()))
    progress = st.progress(
        done_count / len(docs) if docs else 1.0,
        text=f"OCR færdig for {done_count}/{len(docs)} dokumenter · {_format_duration(elapsed_total)} forløbet",
    )
    snapshot_ph = st.empty()
    statuses = _build_status_snapshot(docs)
    if next_doc:
        statuses[next_doc.filename] = ("Kører", "OCRmyPDF og tekstudtræk i gang")
    render_batch_snapshot(snapshot_ph, statuses)

    status_col1, status_col2 = st.columns([3, 2])

    if status_col2.button("Stop batch-OCR", type="secondary", width="stretch"):
        st.session_state.pop(_BATCH_THREAD_KEY, None)
        st.session_state.pop(_BATCH_RESULT_KEY, None)
        st.session_state.pop(_BATCH_DOC_START_KEY, None)
        _clear_batch_state(case.case_id)
        st.session_state["ocr_batch_feedback"] = (
            "warning",
            "Batch-OCR blev stoppet manuelt.",
        )
        st.rerun()

    if not next_doc:
        status_col1.info("Batch-OCR afslutter og synkroniserer status.")
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
    elif _BATCH_THREAD_KEY in st.session_state:
        # Thread kører allerede — poll og vis elapsed time
        thread = st.session_state[_BATCH_THREAD_KEY]
        doc_elapsed = int(time.time() - st.session_state[_BATCH_DOC_START_KEY])
        estimated = max(next_doc.page_count * SECS_PER_PAGE, 10)
        status_col1.info(
            f"OCR kører på `{next_doc.filename}` ({next_doc.page_count} sider)  \n"
            f"Forløbet: **{_format_duration(doc_elapsed)}** / estimeret: ~{_format_duration(estimated)}"
        )
        if not thread.is_alive():
            ok, message = st.session_state.pop(_BATCH_RESULT_KEY, (False, "Ukendt fejl"))
            st.session_state.pop(_BATCH_THREAD_KEY)
            st.session_state.pop(_BATCH_DOC_START_KEY)
            updated_state = deepcopy(batch_state)
            updated_state["pending_doc_ids"] = [
                d for d in pending_ids if d != next_doc.document_id
            ]
            if not ok:
                failures.append(f"{next_doc.filename}: {message}")
            updated_state["failures"] = failures
            _set_batch_state(case.case_id, updated_state)
            st.rerun()
        else:
            time.sleep(1)
            st.rerun()
    else:
        # Start thread for næste dokument
        status_col1.info(
            f"Starter OCR på `{next_doc.filename}` ({next_doc.page_count} sider, "
            f"estimeret ~{_format_duration(next_doc.page_count * SECS_PER_PAGE)})..."
        )

        def _batch_thread(c_id=case.case_id, d=next_doc):
            ok, msg = run_ocr_for_document(c_id, d)
            st.session_state[_BATCH_RESULT_KEY] = (ok, msg)

        t = threading.Thread(target=_batch_thread, daemon=True)
        st.session_state[_BATCH_THREAD_KEY] = t
        st.session_state[_BATCH_DOC_START_KEY] = time.time()
        t.start()
        st.rerun()

if docs_to_process:
    total_pages = sum(d.page_count for d in docs_to_process)
    estimated_str = _format_duration(total_pages * SECS_PER_PAGE)
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
                "start_time": time.time(),
            },
        )
        st.rerun()
    if batch_running:
        actions_col2.caption(
            "Batch-kørsel er aktiv. Siden rerender hvert sekund, så status og tællere følger den faktiske state."
        )
    else:
        actions_col2.caption(
            f"{len(docs_to_process)} dokument(er) · {total_pages} sider · estimeret ~{estimated_str}"
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
        _set_batch_state(
            case.case_id,
            {
                "pending_doc_ids": [d.document_id for d in failed_docs],
                "failures": [],
                "start_time": time.time(),
            },
        )
        st.rerun()

for doc in docs:
    with st.expander(f"{doc.filename} · {parse_status_label(doc.parse_status)}", expanded=doc.parse_status != "ocr_done"):
        col1, col2, col3 = st.columns([3, 1, 1])
        col1.caption(f"Dokument-id: `{doc.document_id}`")
        col2.metric("Sider", str(doc.page_count))
        col3.metric("Status", parse_status_label(doc.parse_status))

        tk = _single_thread_key(doc.document_id)
        rk = _single_result_key(doc.document_id)
        sk = _single_start_key(doc.document_id)

        if tk in st.session_state:
            thread = st.session_state[tk]
            doc_elapsed = int(time.time() - st.session_state[sk])
            estimated = max(doc.page_count * SECS_PER_PAGE, 10)
            st.info(
                f"OCR kører... **{_format_duration(doc_elapsed)}** forløbet "
                f"/ estimeret ~{_format_duration(estimated)} ({doc.page_count} sider)"
            )
            if not thread.is_alive():
                ok, message = st.session_state.pop(rk, (False, "Ukendt fejl"))
                st.session_state.pop(tk)
                st.session_state.pop(sk)
                if ok:
                    st.success(f"OCR færdig: {message}")
                else:
                    st.error(f"Fejl: {message}")
                st.rerun()
            else:
                time.sleep(1)
                st.rerun()
        elif not batch_running:
            if st.button(
                "Kør OCR nu",
                key=f"ocr_{doc.document_id}",
                type="primary",
                width="stretch",
            ):
                def _single_thread(c_id=case.case_id, d=doc):
                    ok, msg = run_ocr_for_document(c_id, d)
                    st.session_state[rk] = (ok, msg)

                t = threading.Thread(target=_single_thread, daemon=True)
                st.session_state[tk] = t
                st.session_state[sk] = time.time()
                t.start()
                st.rerun()
        else:
            st.button(
                "Kør OCR nu",
                key=f"ocr_{doc.document_id}",
                type="primary",
                width="stretch",
                disabled=True,
            )

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
