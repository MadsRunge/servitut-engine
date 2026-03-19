import sys
import threading
import time
from pathlib import Path

from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import storage_service
from app.services.extraction_service import (
    describe_chunk_scoring_inputs,
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


def _join_or_dash(values: list[str]) -> str:
    cleaned = [value for value in values if value]
    return ", ".join(cleaned) if cleaned else "—"


def _format_derived_signals(derived_signals: list[dict]) -> str:
    if not derived_signals:
        return "—"
    return " | ".join(
        f"{signal['label']} ({signal['weight']}): {', '.join(signal['values'])}"
        for signal in derived_signals
    )


def _format_signal_examples(signal_group: dict) -> str:
    examples = []
    for signal in signal_group["signals"][:5]:
        display = ", ".join(signal["display_values"]) or signal["normalized_value"]
        examples.append(display)
    return " | ".join(examples) if examples else "—"


def _format_matched_signals(matched_signals: list[dict]) -> str:
    if not matched_signals:
        return "—"
    parts = []
    for signal in matched_signals:
        canonical = [
            f"{ref['date_reference']} — {ref['title']}"
            for ref in signal["canonical_refs"][:2]
        ]
        values = ", ".join(signal["display_values"]) or signal["normalized_value"]
        suffix = f" → {'; '.join(canonical)}" if canonical else ""
        parts.append(f"{signal['label']} ({signal['weight']}): {values}{suffix}")
    return " | ".join(parts)


def _scoring_results_are_compatible(results: list[dict]) -> bool:
    if not results:
        return True
    required = {"selection_summary", "rules", "chunk_details"}
    return all(required.issubset(result.keys()) for result in results)


def _render_canonical_summary(scoring_inputs: dict) -> None:
    signal_groups = scoring_inputs["signal_groups"]
    canonical_rows = scoring_inputs["canonical_rows"]
    rules = scoring_inputs["rules"]

    render_stat_cards([
        ("Servitutter", str(len(canonical_rows)), "Poster i tinglysningsattesten"),
        ("Akt-signaler", str(next(group["count"] for group in signal_groups if group["signal_type"] == "akt_nr")), "Normaliserede aktnumre"),
        ("Matrikel-signaler", str(next(group["count"] for group in signal_groups if group["signal_type"] == "matrikel")), "Scope fra attesten"),
        ("Titelord", str(next(group["count"] for group in signal_groups if group["signal_type"] == "title_word")), "Afledte nøgleord"),
    ])

    st.info(
        "Chunk-scoring bruger ikke fri semantik. Den scorer kun på konkrete signaler fra tinglysningsattesten: "
        f"minimumscore {rules['minimum_score']}, kontekstvindue {rules['context_window']}, "
        f"max {rules['max_candidate_chunks']} chunks og {rules['max_candidate_chars']:,} tegn pr. akt.",
        icon="ℹ️",
    )

    rule_rows = [
        {
            "Signaltype": item["label"],
            "Vægt": item["weight"],
            "Forklaring": item["description"],
        }
        for item in rules["signal_weights"]
    ]
    st.dataframe(rule_rows, width="stretch", hide_index=True)

    signal_rows = [
        {
            "Signaltype": group["label"],
            "Vægt": group["weight"],
            "Antal signaler": group["count"],
            "Eksempler": _format_signal_examples(group),
        }
        for group in signal_groups
    ]
    st.dataframe(signal_rows, width="stretch", hide_index=True)

    canonical_table = [
        {
            "Løbenummer / dato": row["date_reference"],
            "Titel": row["title"],
            "Akt nr.": row["akt_nr"],
            "Vedr.-matrikler": _join_or_dash(row["applies_to_matrikler"]),
            "Rå matrikelhenvisninger": _join_or_dash(row["raw_matrikel_references"]),
            "Scope-tekst fra attest": row["raw_scope_text"],
            "Afledte signaler": _format_derived_signals(row["derived_signals"]),
        }
        for row in canonical_rows
    ]
    st.dataframe(canonical_table, width="stretch", hide_index=True)


def _render_document_result(result: dict) -> None:
    summary = result["selection_summary"]
    if result["skipped"]:
        label = f"⊘ {result['filename']} — ingen chunks nåede tærsklen"
    else:
        label = (
            f"✅ {result['filename']} — {result['candidate_count']} chunks sendt til LLM "
            f"({result['candidate_chars']:,} tegn, max_score={result['max_score']})"
        )

    with st.expander(label, expanded=False):
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Valgte hits", str(summary["selected_hit_chunks"]))
        col2.metric("Valgt kontekst", str(summary["selected_context_chunks"]))
        col3.metric("Under tærskel", str(summary["below_threshold_chunks"]))
        col4.metric(
            "Caps-fravalg",
            str(summary["candidate_cap_excluded_chunks"] + summary["char_cap_excluded_chunks"]),
        )

        if result["chunk_details"]:
            selected_rows = [
                {
                    "Side": detail["page"],
                    "Chunk": detail["chunk_index"],
                    "Status": detail["selection_label"],
                    "Score": detail["score"],
                    "Hvorfor": detail["selection_reason"],
                    "Match fra attest": _format_matched_signals(detail["matched_signals"]),
                    "Preview": detail["text_preview"],
                }
                for detail in result["chunk_details"]
                if detail["selected"]
            ]
            if selected_rows:
                st.markdown("**Payload sendt til LLM**")
                st.dataframe(selected_rows, width="stretch", hide_index=True)
            else:
                st.caption("Ingen chunks blev sendt videre til LLM for dette dokument.")

            trace_rows = [
                {
                    "Side": detail["page"],
                    "Chunk": detail["chunk_index"],
                    "Status": detail["selection_label"],
                    "Score": detail["score"],
                    "Rank": str(detail["rank"]) if detail["rank"] is not None else "—",
                    "Hvorfor": detail["selection_reason"],
                    "Match fra attest": _format_matched_signals(detail["matched_signals"]),
                    "Preview": detail["text_preview"],
                }
                for detail in result["chunk_details"]
            ]
            st.markdown("**Beslutningsspor for synlige chunks**")
            st.dataframe(trace_rows, width="stretch", hide_index=True)

            for detail in result["chunk_details"]:
                with st.expander(
                    f"Side {detail['page']} · chunk {detail['chunk_index']} · {detail['selection_label']} · score {detail['score']}",
                    expanded=False,
                ):
                    st.caption(detail["selection_reason"])
                    if detail["matched_signals"]:
                        provenance_rows = [
                            {
                                "Signal": signal["label"],
                                "Vægt": signal["weight"],
                                "Signalværdi": ", ".join(signal["display_values"]) or signal["normalized_value"],
                                "Canonical kilder": " | ".join(
                                    f"{ref['date_reference']} — {ref['title']}"
                                    for ref in signal["canonical_refs"]
                                ),
                            }
                            for signal in detail["matched_signals"]
                        ]
                        st.dataframe(provenance_rows, width="stretch", hide_index=True)
                    else:
                        st.caption("Ingen direkte scoringssignaler på denne chunk; den er kun med som kontekst.")
                    st.code(detail["text_preview"], language="text")
        else:
            st.caption("Ingen chunks med signal eller valgt kontekst at vise.")


setup_page(
    "Chunk-scoring",
    "Se præcist hvilke oplysninger fra tinglysningsattesten der bruges til at filtrere akt-chunks, og hvorfor hver chunk bliver sendt videre eller fravalgt.",
    step="filter",
)

case = select_case()
render_case_banner(case)
render_case_stats(case.case_id)

case_id = case.case_id

render_section(
    "Hvad filtrerer vi på fra tinglysningsattesten?",
    "Tinglysningsattesten bliver først omsat til en canonical liste. Herunder kan du se både de rå felter fra attesten og de afledte signaler, som chunk-scoring bruger mod akterne.",
)

canonical_key = f"canonical_list_{case_id}"
if canonical_key not in st.session_state:
    stored = storage_service.load_canonical_list(case_id)
    if stored is not None:
        st.session_state[canonical_key] = stored
    else:
        saved = storage_service.list_servitutter(case_id)
        attest_confirmed = [servitut for servitut in saved if servitut.attest_confirmed]
        if attest_confirmed:
            st.session_state[canonical_key] = attest_confirmed

canonical_list = st.session_state.get(canonical_key, [])
has_canonical = bool(canonical_list)
col_canonical, col_rerun_canonical = st.columns([2, 1])

if not canonical_list:
    st.info(
        "Ingen tinglysningsattest-udtræk fundet endnu. Når du udtrækker attesten, viser siden præcis hvilke felter og signaler chunk-scoring bagefter bruger.",
        icon="ℹ️",
    )

_CA_THREAD = "canonical_thread"
_CA_RESULT = "canonical_result"
_CA_START = "canonical_start"
_CA_EVENTS = "canonical_events"
_CA_STAGE_ICON = {
    "queued": "⏳",
    "running": "⚙️",
    "requesting": "⚙️",
    "completed": "✅",
    "failed": "❌",
    "skipped": "⊘",
}

if _CA_THREAD in st.session_state:
    thread = st.session_state[_CA_THREAD]
    elapsed = int(time.time() - st.session_state[_CA_START])
    status_ph = st.empty()
    rows = [f"**Udtrækker tinglysningsattesten... {elapsed}s forløbet**"]
    for event in st.session_state.get(_CA_EVENTS, []):
        icon = _CA_STAGE_ICON.get(event["stage"], "⏳")
        rows.append(f"- {icon} `{event['doc_id']}` — {event.get('message', '')}")
    status_ph.markdown("\n".join(rows))

    if not thread.is_alive():
        result, error = st.session_state.pop(_CA_RESULT, (None, "Ukendt fejl"))
        st.session_state.pop(_CA_THREAD)
        st.session_state.pop(_CA_START, None)
        st.session_state.pop(_CA_EVENTS, None)
        status_ph.empty()
        if error:
            st.error(f"Fejl under attest-udtræk: {error}")
        else:
            storage_service.save_canonical_list(case_id, result)
            st.session_state[canonical_key] = result
            st.success(f"Udtræk færdigt — {len(result)} servitutter fundet i tinglysningsattesten", icon="✅")
            st.rerun()
    else:
        time.sleep(1)
        st.rerun()
else:
    run_canonical = False
    if col_canonical.button("Udtræk tinglysningsattest", type="primary", disabled=has_canonical):
        run_canonical = True
    elif col_rerun_canonical.button("Udtræk om igen", disabled=not has_canonical):
        run_canonical = True

    if run_canonical:
        st.session_state[_CA_EVENTS] = []

        def _canonical_thread(case_ref=case_id):
            def _callback(event):
                events = list(st.session_state.get(_CA_EVENTS, []))
                events.append(event)
                st.session_state[_CA_EVENTS] = events

            try:
                result = extract_canonical_from_attest(case_ref, _callback)
                st.session_state[_CA_RESULT] = (result, None)
            except Exception as exc:
                st.session_state[_CA_RESULT] = (None, str(exc))

        thread = threading.Thread(target=_canonical_thread, daemon=True)
        add_script_run_ctx(thread, get_script_run_ctx())
        st.session_state[_CA_THREAD] = thread
        st.session_state[_CA_START] = time.time()
        thread.start()
        st.rerun()

scoring_inputs = describe_chunk_scoring_inputs(canonical_list) if canonical_list else None
if scoring_inputs:
    _render_canonical_summary(scoring_inputs)

render_section(
    "Hvad sendes videre fra hver akt?",
    "For hvert akt-dokument viser siden nu både det endelige payload til LLM og beslutningssporet bag: direkte hits, kontekst-chunks, chunks under tærskel og fravalg pga. caps.",
)

scoring_key = f"scoring_results_{case_id}"
scoring_warning_key = f"{scoring_key}_stale_warning"
if scoring_key not in st.session_state:
    stored = storage_service.load_scoring_results(case_id)
    if stored is not None and _scoring_results_are_compatible(stored):
        st.session_state[scoring_key] = stored
    elif stored is not None:
        st.session_state[scoring_warning_key] = True

if st.session_state.get(scoring_warning_key):
    st.warning(
        "De gemte scoring-resultater er fra en ældre version og mangler det nye beslutningsspor. Kør chunk-scoring igen for at få den fulde forklaring i UI'et."
    )

_SC_THREAD = "scoring_thread"
_SC_RESULT = "scoring_result"
_SC_START = "scoring_start"

run_disabled = not canonical_list
has_results = scoring_key in st.session_state
col_run, col_rerun = st.columns([2, 1])

if _SC_THREAD in st.session_state:
    thread = st.session_state[_SC_THREAD]
    elapsed = int(time.time() - st.session_state[_SC_START])
    st.info(f"Scorer chunks... **{elapsed}s** forløbet")
    if not thread.is_alive():
        results, error = st.session_state.pop(_SC_RESULT, (None, "Ukendt fejl"))
        st.session_state.pop(_SC_THREAD)
        st.session_state.pop(_SC_START, None)
        if error:
            st.error(f"Fejl under scoring: {error}")
        else:
            storage_service.save_scoring_results(case_id, results)
            st.session_state[scoring_key] = results
            st.session_state.pop(scoring_warning_key, None)
            st.rerun()
    else:
        time.sleep(1)
        st.rerun()
else:
    run_scoring = False
    if col_run.button("Kør chunk-scoring", type="primary", disabled=run_disabled or has_results):
        run_scoring = True
    elif col_rerun.button("Kør om igen", disabled=run_disabled or not has_results):
        run_scoring = True

    if run_scoring:
        def _scoring_thread(case_ref=case_id, canon=canonical_list):
            try:
                results = score_akt_chunks_for_case(case_ref, canon)
                st.session_state[_SC_RESULT] = (results, None)
            except Exception as exc:
                st.session_state[_SC_RESULT] = (None, str(exc))

        thread = threading.Thread(target=_scoring_thread, daemon=True)
        add_script_run_ctx(thread, get_script_run_ctx())
        st.session_state[_SC_THREAD] = thread
        st.session_state[_SC_START] = time.time()
        thread.start()
        st.rerun()

scoring_results = st.session_state.get(scoring_key)
if not scoring_results and not canonical_list:
    render_empty_state(
        "Ingen canonical-liste",
        "Udtræk tinglysningsattesten ovenfor for at aktivere den gennemsigtige chunk-scoring.",
    )
elif scoring_results is not None:
    if not scoring_results:
        render_empty_state("Ingen akt-dokumenter", "Upload akt-dokumenter og kør OCR.")
    else:
        llm_docs = sum(1 for result in scoring_results if not result["skipped"])
        skipped_docs = sum(1 for result in scoring_results if result["skipped"])
        total_candidates = sum(result["candidate_count"] for result in scoring_results)
        total_chars = sum(result["candidate_chars"] for result in scoring_results)
        total_context = sum(result["selection_summary"]["selected_context_chunks"] for result in scoring_results)

        render_stat_cards([
            ("Sendes til LLM", str(llm_docs), "Akt-dokumenter med valgt payload"),
            ("Springes over", str(skipped_docs), "Ingen chunk nåede tærsklen"),
            ("Payload-chunks", str(total_candidates), "Samlet antal chunks sendt videre"),
            ("Kontekst-chunks", str(total_context), "Valgt uden egen score pga. nabohit"),
            ("Payload-tegn", f"{total_chars:,}", "Samlet tegnmængde til LLM"),
        ])

        st.caption("Kør udtræk i trin 7 for at bruge de valgte chunks i LLM-berigelsen.")

        for result in scoring_results:
            _render_document_result(result)
