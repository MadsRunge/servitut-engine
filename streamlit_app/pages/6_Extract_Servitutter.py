import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.core.config import settings
from app.services import case_service, matrikel_service, storage_service
from app.services.extraction_service import extract_servitutter
from streamlit_app.ui import (
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_section,
    select_case,
    select_target_matrikel,
    setup_page,
)

setup_page(
    "Udtræk servitutter",
    "Kør den strukturerede ekstraktion på OCR-baserede chunks og gem de identificerede servitutter til review og rapportering.",
    step="extract",
)

case = select_case()
case = select_target_matrikel(case)
render_case_banner(case)
render_case_stats(case.case_id)

all_chunks = storage_service.load_all_chunks(case.case_id)
render_section("Klar til udtræk", f"{len(all_chunks)} chunk(s) er tilgængelige på tværs af den aktive sags dokumenter.")
if case.target_matrikel:
    st.caption(f"Aktiv ekstraktionskontekst: matrikel `{case.target_matrikel}`")
if matrikel_service.extraction_is_stale(case) and case.last_extracted_target_matrikel:
    st.warning(
        "Målmatriklen er ændret siden sidste extraction. "
        f"Kør extraction igen for at opdatere scope-vurderingerne fra "
        f"`{case.last_extracted_target_matrikel}` til `{case.target_matrikel}`."
    )


def _worker_sort_key(worker_name: str) -> tuple[int, str]:
    suffix = worker_name.rsplit("_", 1)[-1]
    return (int(suffix), worker_name) if suffix.isdigit() else (999, worker_name)


def _render_worker_cards(
    container,
    worker_states: dict[str, dict],
    worker_slots: int,
) -> None:
    with container:
        st.markdown("#### Worker-status")
        cols = st.columns(worker_slots)
        ordered_workers = sorted(worker_states, key=_worker_sort_key)
        for idx in range(worker_slots):
            with cols[idx]:
                if idx < len(ordered_workers):
                    state = worker_states[ordered_workers[idx]]
                    st.markdown(f"**{ordered_workers[idx]}**")
                    st.caption(f"Dokument: {state['doc_id']} · Type: {state['source_type']}")
                    st.progress(int(state["progress"] * 100))
                    st.markdown(f"`{state['stage']}`")
                    st.caption(state["message"])
                else:
                    st.markdown(f"**Worker {idx + 1}**")
                    st.progress(0)
                    st.caption("Afventer opgave")


def _render_document_status(container, doc_states: dict[str, dict]) -> None:
    with container:
        st.markdown("#### Dokumentstatus")
        if not doc_states:
            st.caption("Ingen dokumenter i kø endnu.")
            return

        for doc_id, state in doc_states.items():
            progress = int(state["progress"] * 100)
            st.markdown(f"**{doc_id}** · {state['source_type']}")
            st.progress(progress)
            worker = state.get("worker")
            if worker:
                st.caption(f"{state['message']} · {worker}")
            else:
                st.caption(state["message"])


def _render_activity_log(container, events: list[str]) -> None:
    with container:
        st.markdown("#### Aktivitet")
        if events:
            st.code("\n".join(events[-12:]), language="text")
        else:
            st.caption("Ingen aktivitet endnu.")


if st.button("Kør ekstraktion", type="primary"):
    if not all_chunks:
        st.error("Ingen chunks — kør OCR først.")
    else:
        doc_count = len(dict.fromkeys(chunk.document_id for chunk in all_chunks))
        worker_slots = max(1, min(settings.EXTRACTION_MAX_CONCURRENCY, doc_count))
        worker_states: dict[str, dict] = {}
        doc_states: dict[str, dict] = {}
        activity_events: list[str] = []
        summary_placeholder = st.empty()
        worker_container = st.empty()
        document_container = st.empty()
        activity_container = st.empty()

        def handle_progress(event: dict) -> None:
            doc_states[event["doc_id"]] = event
            worker_name = event.get("worker")
            if worker_name:
                worker_states[worker_name] = event
            activity_events.append(
                f"{(worker_name or 'queue')} · {event['doc_id']} · {event['message']}"
            )
            completed = sum(1 for item in doc_states.values() if item["stage"] in {"completed", "failed"})
            summary_placeholder.info(
                f"Extraction kører: {completed}/{doc_count} dokumenter afsluttet · "
                f"{worker_slots} worker(s)"
            )
            _render_worker_cards(worker_container, worker_states, worker_slots)
            _render_document_status(document_container, doc_states)
            _render_activity_log(activity_container, activity_events)

        try:
            servitutter = extract_servitutter(
                all_chunks,
                case.case_id,
                progress_callback=handle_progress,
            )
            for srv in servitutter:
                storage_service.save_servitut(srv)
            summary_placeholder.success(f"Udtrukket {len(servitutter)} servitutter")
            st.rerun()
        except Exception as e:
            summary_placeholder.error(f"Fejl under ekstraktion: {e}")

render_section("Udtrukne servitutter", "Gennemgå felter, confidence, scope og evidens før rapportgenerering.")
servitutter = matrikel_service.filter_servitutter_for_target(
    storage_service.list_servitutter(case.case_id),
    case.target_matrikel,
)
if not servitutter:
    render_empty_state("Ingen servitutter endnu", "Kør ekstraktion, når chunks er klar.")
else:
    for srv in servitutter:
        conf_color = "green" if srv.confidence >= 0.8 else "orange" if srv.confidence >= 0.5 else "red"
        markering = srv.byggeri_markering or "—"
        markering_color = {"rød": "red", "orange": "orange", "sort": "gray"}.get(srv.byggeri_markering or "", "gray")
        with st.expander(
            f"**{srv.title or 'Ukendt titel'}** | :{markering_color}[{markering}] | conf=:{conf_color}[{srv.confidence:.2f}]"
        ):
            col1, col2 = st.columns(2)
            col1.markdown(f"**Dato/ref:** {srv.date_reference or '—'}")
            col1.markdown(
                "**Gælder målmatrikel:** "
                f"{'Ja' if srv.applies_to_target_matrikel else 'Nej' if srv.applies_to_target_matrikel is False else 'Uafklaret'}"
            )
            col1.markdown(f"**Matrikler:** {', '.join(srv.applies_to_matrikler) if srv.applies_to_matrikler else '—'}")
            col1.markdown(f"**Påtaleberettiget:** {srv.beneficiary or '—'}")
            col1.markdown(f"**Rådighed/tilstand:** {srv.disposition_type or '—'}")
            col2.markdown(f"**Retlig type:** {srv.legal_type or '—'}")
            col2.markdown(f"**Byggerelevant:** {'Ja' if srv.construction_relevance else 'Nej'}")
            col2.markdown(f"**Markering:** {srv.byggeri_markering or '—'}")
            col2.markdown(f"**Handling:** {srv.action_note or '—'}")
            st.markdown(f"**Resumé:** {srv.summary or '—'}")
            st.markdown(f"**Scope-grundlag:** {srv.scope_basis or '—'}")
            st.caption(f"ID: {srv.servitut_id} | Kilde: {srv.source_document}")
            if srv.evidence:
                st.markdown("**Evidens:**")
                for ev in srv.evidence:
                    st.code(f"[Side {ev.page}] {ev.text_excerpt[:200]}", language="text")
