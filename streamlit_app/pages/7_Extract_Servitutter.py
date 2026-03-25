import re
from queue import Empty, Queue
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _md(value: object) -> str:
    """Escape markdown special characters in dynamic/LLM-generated values."""
    if value is None:
        return "—"
    return re.sub(r'([\\*_\[\]()#`|>~])', r'\\\1', str(value))

import streamlit as st

from app.services import storage_service
from app.services.extraction_service import extract_servitutter
from streamlit_app.ui import (
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_section,
    render_stat_cards,
    select_case,
    setup_page,
)

setup_page(
    "Udtræk servitutter",
    "Kør den strukturerede ekstraktion på OCR-baserede chunks og gem de identificerede servitutter til review og rapportering.",
    step="extract",
)

case = select_case()
render_case_banner(case)
render_case_stats(case.case_id)

all_chunks = storage_service.load_all_chunks(case.case_id)
documents = storage_service.list_documents(case.case_id)
doc_name: dict[str, str] = {d.document_id: d.filename for d in documents}

# --- Load cached canonical og scoring ---
cached_canonical = storage_service.load_canonical_list(case.case_id)
scoring_results = storage_service.load_scoring_results(case.case_id)

# --- Klargøringsstatus ---
render_section("Klar til udtræk", "Pipeline-oversigt inden LLM-kørsel.")

if cached_canonical and scoring_results:
    llm_docs = sum(1 for r in scoring_results if not r["skipped"])
    skipped_docs = sum(1 for r in scoring_results if r["skipped"])
    total_candidates = sum(r["candidate_count"] for r in scoring_results)
    total_chars = sum(r["candidate_chars"] for r in scoring_results)
    render_stat_cards([
        ("Canonical", str(len(cached_canonical)), "Servitutter fra attest (cached)"),
        ("Docs → LLM", str(llm_docs), f"{skipped_docs} springes over"),
        ("Kandidat-chunks", str(total_candidates), f"af {len(all_chunks)} total"),
        ("Kandidat-tegn", f"{total_chars:,}", "Sendes til LLM"),
    ])
    st.success(
        f"Canonical liste og chunk-scoring klar — springer attest-udtræk over og bruger {total_candidates} pre-filtrerede chunks.",
        icon="✅",
    )
elif cached_canonical:
    render_stat_cards([
        ("Canonical", str(len(cached_canonical)), "Servitutter fra attest (cached)"),
        ("Chunks i alt", str(len(all_chunks)), "Fase 1 filtrerer ved kørsel"),
    ])
    st.info("Chunk-scoring ikke kørt — Fase 1 filtrerer chunks automatisk ved udtræk.", icon="ℹ️")
    st.page_link("pages/6_Filter_Chunks.py", label="→ Kør chunk-scoring først (anbefalet)", icon="🔬")
else:
    render_stat_cards([
        ("Chunks i alt", str(len(all_chunks)), "Klar til udtræk"),
    ])
    st.warning(
        "Ingen cached canonical liste — attest-udtræk kører som Pas 1 (bruger ekstra tokens).",
        icon="⚠️",
    )
    st.page_link("pages/6_Filter_Chunks.py", label="→ Udtræk canonical og kør scoring først", icon="🔬")

# --- Extraction ---
STAGE_ICON = {
    "queued":    "⏳",
    "running":   "⚙️",
    "requesting":"⚙️",
    "parsing":   "⚙️",
    "completed": "✅",
    "failed":    "❌",
    "skipped":   "⊘",
}

_EX_THREAD   = "extract_thread"
_EX_RESULT   = "extract_result"
_EX_START    = "extract_start"
_EX_EVENTS   = "extract_events"
_EX_DOCCOUNT = "extract_doc_count"
_EX_QUEUE    = "extract_queue"


def _drain_extract_messages() -> None:
    message_queue = st.session_state.get(_EX_QUEUE)
    if message_queue is None:
        return

    events = list(st.session_state.get(_EX_EVENTS, []))
    latest_result = st.session_state.get(_EX_RESULT)

    while True:
        try:
            message = message_queue.get_nowait()
        except Empty:
            break

        if message["type"] == "event":
            events.append(message["payload"])
        elif message["type"] == "result":
            latest_result = (message.get("result"), message.get("error"))

    st.session_state[_EX_EVENTS] = events
    if latest_result is not None:
        st.session_state[_EX_RESULT] = latest_result

if _EX_THREAD in st.session_state:
    thread = st.session_state[_EX_THREAD]
    _drain_extract_messages()
    elapsed = int(time.time() - st.session_state[_EX_START])
    doc_count = st.session_state.get(_EX_DOCCOUNT, 1)
    events = st.session_state.get(_EX_EVENTS, [])

    completed = sum(1 for e in events if e["stage"] in {"completed", "failed", "skipped"})
    summary_ph = st.empty()
    progress_ph = st.empty()
    docs_ph = st.empty()

    summary_ph.markdown(
        f"**Behandler dokumenter — {completed} af {doc_count} færdige · {elapsed}s forløbet**"
    )
    progress_ph.progress(completed / doc_count if doc_count else 1.0)
    if events:
        rows = []
        for e in events:
            icon = STAGE_ICON.get(e["stage"], "⏳")
            name = doc_name.get(e["doc_id"], e["doc_id"])
            typ = "Tinglysningsattest" if e["source_type"] == "tinglysningsattest" else "Akt"
            rows.append(f"- {icon} **{name}** — {typ}: {e.get('message', '')}")
        docs_ph.markdown("\n".join(rows))

    if not thread.is_alive():
        _drain_extract_messages()
        result, error = st.session_state.pop(_EX_RESULT, (None, "Ukendt fejl"))
        st.session_state.pop(_EX_THREAD)
        st.session_state.pop(_EX_START, None)
        st.session_state.pop(_EX_EVENTS, None)
        st.session_state.pop(_EX_DOCCOUNT, None)
        st.session_state.pop(_EX_QUEUE, None)
        if error:
            st.error(f"Fejl under udtræk: {error}")
        else:
            for srv in result:
                storage_service.save_servitut(srv)
            st.success(f"Udtræk færdigt — {len(result)} servitutter fundet", icon="✅")
            st.rerun()
    else:
        time.sleep(1)
        st.rerun()

elif st.button("Kør udtræk", type="primary", disabled=not all_chunks):
    tracked_doc_ids = set(c.document_id for c in all_chunks)
    attest_doc_ids = {d.document_id for d in documents if d.document_type == "tinglysningsattest"}
    if cached_canonical:
        tracked_doc_ids -= attest_doc_ids
    doc_count = len(tracked_doc_ids)
    st.session_state[_EX_DOCCOUNT] = doc_count
    st.session_state[_EX_EVENTS] = []
    result_queue: Queue = Queue()
    st.session_state[_EX_QUEUE] = result_queue

    def _extract_thread(
        c_id=case.case_id,
        chunks=all_chunks,
        canonical=cached_canonical,
        message_queue=result_queue,
    ):
        def _cb(event):
            message_queue.put({"type": "event", "payload": event})

        try:
            result = extract_servitutter(chunks, c_id, progress_callback=_cb, cached_canonical=canonical)
            message_queue.put({"type": "result", "result": result, "error": None})
        except Exception as e:
            message_queue.put({"type": "result", "result": None, "error": str(e)})

    t = threading.Thread(target=_extract_thread, daemon=True)
    st.session_state[_EX_THREAD] = t
    st.session_state[_EX_START] = time.time()
    t.start()
    st.rerun()


# --- Servitut-liste ---
render_section(
    "Udtrukne servitutter",
    "Gennemgå alle udtrukne servitutter for ejendommen inden rapportgenerering.",
)

servitutter = storage_service.list_servitutter(case.case_id)

if not servitutter:
    render_empty_state("Ingen servitutter endnu", "Kør udtræk, når chunks er klar.")
else:
    MARKERING_BADGE = {
        "rød":    ("🔴", "Byggerelevant — direkte konsekvens"),
        "orange": ("🟠", "Kræver stillingtagen"),
        "sort":   ("⚫", "Ingen byggerelevans"),
    }
    TARGET_LABEL = {True: "✅ Ja", False: "❌ Nej", None: "❓ Uafklaret"}

    unconfirmed = [s for s in servitutter if not s.attest_confirmed]
    if unconfirmed:
        st.warning(
            f"**{len(unconfirmed)} servitut(ter) fundet i akter men ikke i tinglysningsattesten.** "
            f"Disse er markeret med ⚠️ og bør verificeres manuelt.",
            icon="⚠️",
        )

    rød_n = sum(1 for s in servitutter if s.byggeri_markering == "rød")
    orange_n = sum(1 for s in servitutter if s.byggeri_markering == "orange")
    sort_n = sum(1 for s in servitutter if s.byggeri_markering == "sort")
    ja_n = sum(1 for s in servitutter if s.applies_to_target_matrikel is True)
    nej_n = sum(1 for s in servitutter if s.applies_to_target_matrikel is False)
    uafklaret_n = sum(1 for s in servitutter if s.applies_to_target_matrikel is None)
    render_stat_cards([
        ("🔴 Rød", str(rød_n), "Direkte byggerelevans"),
        ("🟠 Orange", str(orange_n), "Kræver stillingtagen"),
        ("⚫ Sort", str(sort_n), "Ingen byggerelevans"),
        ("Gælder matrikel", str(ja_n), "Ja"),
        ("Uafklaret scope", str(uafklaret_n), "Måske"),
        ("Gælder ikke", str(nej_n), "Nej"),
    ])

    for srv in servitutter:
        icon, badge_label = MARKERING_BADGE.get(srv.byggeri_markering or "", ("—", "Ikke vurderet"))
        title_text = srv.title or "Ukendt titel"
        unconfirmed_prefix = "⚠️ " if not srv.attest_confirmed else ""

        with st.expander(f"{unconfirmed_prefix}{icon} {title_text}", expanded=False):
            col_a, col_b, col_c = st.columns([2, 1, 1])
            col_a.markdown(f"**Løbenummer / dato**\n\n{_md(srv.date_reference)}")
            col_b.markdown(f"**Gælder målmatrikel**\n\n{TARGET_LABEL[srv.applies_to_target_matrikel]}")
            col_c.markdown(f"**Byggemarkering**\n\n{icon} {_md(badge_label)}")

            st.divider()

            col1, col2 = st.columns(2)
            col1.markdown(f"**Påtaleberettiget**\n\n{_md(srv.beneficiary)}")
            col1.markdown(f"**Rådighed / tilstand**\n\n{_md(srv.disposition_type)}")
            col2.markdown(f"**Retlig type**\n\n{_md(srv.legal_type)}")
            col2.markdown(f"**Handling**\n\n{_md(srv.action_note)}")

            st.divider()

            if srv.summary:
                st.markdown(f"**Beskrivelse**\n\n{_md(srv.summary)}")
            if srv.scope_basis:
                st.caption(f"Scope-grundlag: {_md(srv.scope_basis)}")
            if srv.applies_to_matrikler:
                st.caption(f"Gælder matrikler: {', '.join(srv.applies_to_matrikler)}")

            if srv.evidence:
                with st.expander("Vis kildetekst"):
                    for ev in srv.evidence:
                        name = doc_name.get(ev.document_id, ev.document_id)
                        st.caption(f"{name} — side {ev.page}")
                        st.code(ev.text_excerpt[:300], language="text")

            st.caption(
                f"Confidence: {srv.confidence:.0%} | "
                f"Kilde: {doc_name.get(srv.source_document, srv.source_document)} | "
                f"ID: {srv.servitut_id}"
            )
