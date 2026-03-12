import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import storage_service
from app.services.extraction_service import (
    extract_canonical_from_attest,
    score_akt_chunks_for_case,
)
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
    "Chunk-scoring",
    "Deterministisk filtrering af akt-chunks mod canonical-signaler inden LLM-berigelse.",
    step="filter",
)

case = select_case()
render_case_banner(case)
render_case_stats(case.case_id)

case_id = case.case_id

# ---------------------------------------------------------------------------
# Sektion A — Canonical-liste
# ---------------------------------------------------------------------------
render_section(
    "Canonical-liste (tinglysningsattest)",
    "Kildelisten bruges som signaler for chunk-scoring i akt-dokumenterne.",
)

canonical_key = f"canonical_list_{case_id}"

# Load from storage if not already in session_state
if canonical_key not in st.session_state:
    stored = storage_service.load_canonical_list(case_id)
    if stored is not None:
        st.session_state[canonical_key] = stored
    else:
        # Fallback: brug allerede gemte attest_confirmed servitutter
        saved = storage_service.list_servitutter(case_id)
        attest_confirmed = [s for s in saved if s.attest_confirmed]
        if attest_confirmed:
            st.session_state[canonical_key] = attest_confirmed

canonical_list = st.session_state.get(canonical_key, [])

has_canonical = bool(canonical_list)
col_canonical, col_rerun_canonical = st.columns([2, 1])

if not canonical_list:
    st.info(
        "Ingen tinglysningsattest-udtræk fundet. "
        "Udtræk canonical-listen fra tinglysningsattesten.",
        icon="ℹ️",
    )

if col_canonical.button("Udtræk tinglysningsattest", type="primary", disabled=has_canonical):
    _run_canonical = True
elif col_rerun_canonical.button("Udtræk om igen", disabled=not has_canonical):
    _run_canonical = True
else:
    _run_canonical = False

if _run_canonical:
    STAGE_ICON = {"queued": "⏳", "running": "⚙️", "requesting": "⚙️",
                  "completed": "✅", "failed": "❌", "skipped": "⊘"}
    doc_states: dict[str, dict] = {}
    status_ph = st.empty()

    def _handle_attest_progress(event: dict) -> None:
        doc_states[event["doc_id"]] = event
        rows = []
        for did, state in doc_states.items():
            icon = STAGE_ICON.get(state["stage"], "⏳")
            rows.append(f"- {icon} `{did}` — {state['message']}")
        status_ph.markdown("\n".join(rows))

    with st.spinner("Udtræk tinglysningsattest..."):
        try:
            result = extract_canonical_from_attest(case_id, _handle_attest_progress)
            storage_service.save_canonical_list(case_id, result)
            st.session_state[canonical_key] = result
            status_ph.empty()
            st.success(f"Udtræk færdigt — {len(result)} canonical servitutter fundet", icon="✅")
            st.rerun()
        except Exception as e:
            status_ph.empty()
            st.error(f"Fejl under udtræk: {e}")

if canonical_list:
    st.caption(f"{len(canonical_list)} canonical servitutter fundet")
    canonical_rows = [
        {
            "Løbenummer / dato": s.date_reference or "—",
            "Titel": s.title or "—",
            "Akt nr.": s.akt_nr or "—",
        }
        for s in canonical_list
    ]
    st.dataframe(canonical_rows, width="stretch", hide_index=True)

# ---------------------------------------------------------------------------
# Sektion B — Chunk-scoring per akt-dokument
# ---------------------------------------------------------------------------
render_section(
    "Chunk-scoring per akt-dokument",
    "Scorer alle chunks i akt-dokumenter mod canonical-signalerne og viser hvilke der sendes til LLM.",
)

scoring_key = f"scoring_results_{case_id}"

# Load from storage if not already in session_state
if scoring_key not in st.session_state:
    stored = storage_service.load_scoring_results(case_id)
    if stored is not None:
        st.session_state[scoring_key] = stored

run_disabled = not canonical_list
has_results = scoring_key in st.session_state
col_run, col_rerun = st.columns([2, 1])
if col_run.button("Kør chunk-scoring", type="primary", disabled=run_disabled or has_results):
    with st.spinner("Scorer chunks..."):
        try:
            results = score_akt_chunks_for_case(case_id, canonical_list)
            storage_service.save_scoring_results(case_id, results)
            st.session_state[scoring_key] = results
            st.rerun()
        except Exception as e:
            st.error(f"Fejl under scoring: {e}")
if col_rerun.button("Kør om igen", disabled=run_disabled or not has_results):
    with st.spinner("Scorer chunks..."):
        try:
            results = score_akt_chunks_for_case(case_id, canonical_list)
            storage_service.save_scoring_results(case_id, results)
            st.session_state[scoring_key] = results
            st.rerun()
        except Exception as e:
            st.error(f"Fejl under scoring: {e}")

scoring_results = st.session_state.get(scoring_key)

if not scoring_results and not canonical_list:
    render_empty_state(
        "Ingen canonical-liste",
        "Udtræk tinglysningsattesten i Sektion A for at aktivere chunk-scoring.",
    )
elif scoring_results is not None:
    if not scoring_results:
        render_empty_state("Ingen akt-dokumenter", "Upload akt-dokumenter og kør OCR.")
    else:
        llm_docs = sum(1 for r in scoring_results if not r["skipped"])
        skipped_docs = sum(1 for r in scoring_results if r["skipped"])
        total_candidates = sum(r["candidate_count"] for r in scoring_results)
        total_chars = sum(r["candidate_chars"] for r in scoring_results)

        render_stat_cards([
            ("Sendes til LLM", str(llm_docs), "Docs med kandidat-chunks"),
            ("Springes over", str(skipped_docs), "Docs uden signal"),
            ("Kandidat-chunks", str(total_candidates), "Samlede chunks til LLM"),
            ("Kandidat-tegn", f"{total_chars:,}", "Tegn sendes til LLM"),
        ])

        st.caption("Kør udtræk i trin 7 for at køre LLM-berigelsen på kandidat-chunks.")

        for r in scoring_results:
            if r["skipped"]:
                icon = "⊘"
                label = f"{icon} {r['filename']} — ingen kandidater (sprunget over)"
            else:
                icon = "✅"
                label = (
                    f"{icon} {r['filename']} — "
                    f"{r['candidate_count']}/{r['total_chunks']} chunks | "
                    f"max\\_score={r['max_score']} | {r['candidate_chars']:,} tegn"
                )

            with st.expander(label, expanded=False):
                if r["chunk_details"]:
                    rows = [
                        {
                            "Side": d["page"],
                            "Score": d["score"],
                            "Signaler": ", ".join(d["reasons"]),
                            "Tekst-preview": d["text_preview"],
                            "Valgt": "✅" if d["selected"] else "—",
                        }
                        for d in r["chunk_details"]
                    ]
                    st.dataframe(rows, width="stretch", hide_index=True)
                else:
                    st.caption("Ingen chunks med score > 0.")
