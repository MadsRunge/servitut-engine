import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service
from app.services.extraction_service import extract_servitutter
from streamlit_app.ui import (
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_section,
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
render_section("Klar til udtræk", f"{len(all_chunks)} chunk(s) er tilgængelige på tværs af den aktive sags dokumenter.")

if st.button("Kør ekstraktion", type="primary"):
    if not all_chunks:
        st.error("Ingen chunks — kør OCR først.")
    else:
        with st.spinner("Kalder LLM-provider..."):
            try:
                servitutter = extract_servitutter(all_chunks, case.case_id)
                for srv in servitutter:
                    storage_service.save_servitut(srv)
                st.success(f"Udtrukket {len(servitutter)} servitutter")
                st.rerun()
            except Exception as e:
                st.error(f"Fejl: {e}")

render_section("Udtrukne servitutter", "Gennemgå felter, confidence og evidens før rapportgenerering.")
servitutter = storage_service.list_servitutter(case.case_id)
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
            col1.markdown(f"**Påtaleberettiget:** {srv.beneficiary or '—'}")
            col1.markdown(f"**Rådighed/tilstand:** {srv.disposition_type or '—'}")
            col2.markdown(f"**Retlig type:** {srv.legal_type or '—'}")
            col2.markdown(f"**Byggerelevant:** {'Ja' if srv.construction_relevance else 'Nej'}")
            col2.markdown(f"**Markering:** {srv.byggeri_markering or '—'}")
            col2.markdown(f"**Handling:** {srv.action_note or '—'}")
            st.markdown(f"**Resumé:** {srv.summary or '—'}")
            st.caption(f"ID: {srv.servitut_id} | Kilde: {srv.source_document}")
            if srv.evidence:
                st.markdown("**Evidens:**")
                for ev in srv.evidence:
                    st.code(f"[Side {ev.page}] {ev.text_excerpt[:200]}", language="text")
