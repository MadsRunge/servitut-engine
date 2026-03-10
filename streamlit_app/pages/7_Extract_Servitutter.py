import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

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

if st.button("Kør udtræk", type="primary", disabled=not all_chunks):
    # Doc-count: attest tæller med hvis vi ikke har cache (Pas 1 kører)
    tracked_doc_ids = set(c.document_id for c in all_chunks)
    if cached_canonical:
        # Attest-docs springes over i progress — tæl kun akt-docs
        tracked_doc_ids = {
            c.document_id for c in all_chunks
            if doc_name.get(c.document_id, "") or True  # alle akt-docs
        }
        # Filtrer attest-doc ud fra tællingen
        attest_doc_ids = {
            d.document_id for d in documents
            if d.document_type == "tinglysningsattest"
        }
        tracked_doc_ids -= attest_doc_ids
    doc_count = len(tracked_doc_ids)

    doc_states: dict[str, dict] = {}
    summary_ph = st.empty()
    progress_ph = st.empty()
    docs_ph = st.empty()

    summary_ph.markdown(f"**Starter udtræk — 0 af {doc_count} færdige**")
    progress_ph.progress(0.0)
    docs_ph.caption("Klargør dokumentkø...")

    def handle_progress(event: dict) -> None:
        doc_id = event["doc_id"]
        doc_states[doc_id] = event
        completed = sum(
            1 for s in doc_states.values()
            if s["stage"] in {"completed", "failed", "skipped"}
        )
        summary_ph.markdown(f"**Behandler dokumenter — {completed} af {doc_count} færdige**")
        progress_ph.progress(completed / doc_count if doc_count else 1.0)

        rows = []
        for did, state in doc_states.items():
            icon = STAGE_ICON.get(state["stage"], "⏳")
            name = doc_name.get(did, did)
            typ = "Tinglysningsattest" if state["source_type"] == "tinglysningsattest" else "Akt"
            msg = state.get("message", "")
            rows.append(
                f"{icon} &nbsp; **{name}** &nbsp; "
                f"<span style='color:gray;font-size:0.85em'>{typ} — {msg}</span>"
            )
        docs_ph.markdown("\n\n".join(rows), unsafe_allow_html=True)

    try:
        servitutter = extract_servitutter(
            all_chunks,
            case.case_id,
            progress_callback=handle_progress,
            cached_canonical=cached_canonical,
        )
        for srv in servitutter:
            storage_service.save_servitut(srv)

        summary_ph.empty()
        progress_ph.empty()
        docs_ph.empty()
        st.success(f"Udtræk færdigt — {len(servitutter)} servitutter fundet", icon="✅")
        st.rerun()
    except Exception as e:
        progress_ph.empty()
        docs_ph.empty()
        summary_ph.error(f"Fejl under udtræk: {e}")


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
        unconfirmed_prefix = "⚠️ &nbsp;" if not srv.attest_confirmed else ""

        with st.expander(f"{unconfirmed_prefix}{icon} &nbsp; {title_text}", expanded=False):
            col_a, col_b, col_c = st.columns([2, 1, 1])
            col_a.markdown(f"**Løbenummer / dato**\n\n{srv.date_reference or '—'}")
            col_b.markdown(f"**Gælder målmatrikel**\n\n{TARGET_LABEL[srv.applies_to_target_matrikel]}")
            col_c.markdown(f"**Byggemarkering**\n\n{icon} {badge_label}")

            st.divider()

            col1, col2 = st.columns(2)
            col1.markdown(f"**Påtaleberettiget**\n\n{srv.beneficiary or '—'}")
            col1.markdown(f"**Rådighed / tilstand**\n\n{srv.disposition_type or '—'}")
            col2.markdown(f"**Retlig type**\n\n{srv.legal_type or '—'}")
            col2.markdown(f"**Handling**\n\n{srv.action_note or '—'}")

            st.divider()

            if srv.summary:
                st.markdown(f"**Beskrivelse**\n\n{srv.summary}")
            if srv.scope_basis:
                st.caption(f"Scope-grundlag: {srv.scope_basis}")
            if srv.applies_to_matrikler:
                st.caption(f"Gælder matrikler: {', '.join(srv.applies_to_matrikler)}")

            if srv.evidence:
                with st.expander("Vis kildetekst"):
                    for ev in srv.evidence:
                        name = doc_name.get(ev.document_id, ev.document_id)
                        st.caption(f"{name} — side {ev.page}")
                        st.code(ev.text_excerpt[:300], language="text")

            st.caption(
                f"Confidence: {srv.confidence:.0%} &nbsp;|&nbsp; "
                f"Kilde: {doc_name.get(srv.source_document, srv.source_document)} &nbsp;|&nbsp; "
                f"ID: {srv.servitut_id}",
                unsafe_allow_html=True,
            )
