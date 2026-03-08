import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, matrikel_service, storage_service
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
    "Review og sporbarhed",
    "Spor hver servitut tilbage til evidens, chunk og original side, så kvaliteten kan vurderes med fuld kontekst.",
    step="review",
)

case = select_case()
case = select_target_matrikel(case)
render_case_banner(case)
render_case_stats(case.case_id)


servitutter = matrikel_service.filter_servitutter_for_target(
    storage_service.list_servitutter(case.case_id),
    case.target_matrikel,
)
if not servitutter:
    render_empty_state("Ingen servitutter", "Kør ekstraktion, før review og sporbarhed giver mening.")
    st.stop()

srv_options = {
    f"{srv.title or srv.servitut_id} (conf={srv.confidence:.2f})": srv.servitut_id
    for srv in servitutter
}
selected_srv_label = st.selectbox("Vælg servitut", list(srv_options.keys()))
srv_id = srv_options[selected_srv_label]

srv = storage_service.load_servitut(case.case_id, srv_id)
if not srv:
    st.error("Servitut ikke fundet.")
    st.stop()

render_section("Servitutprofil", "Sammenfatning af det valgte fund før dyk ned i evidenskæden.")
col1, col2 = st.columns([2, 1])
with col1:
    st.subheader(srv.title or "Ukendt titel")
    st.markdown(f"**Resumé:** {srv.summary or '—'}")
    st.markdown(f"**Dato/ref:** {srv.date_reference or '—'}")
    st.markdown(f"**Matrikler:** {', '.join(srv.applies_to_matrikler) if srv.applies_to_matrikler else '—'}")
    st.markdown(
        "**Gælder målmatrikel:** "
        f"{'Ja' if srv.applies_to_target_matrikel else 'Nej' if srv.applies_to_target_matrikel is False else 'Uafklaret'}"
    )
    st.markdown(f"**Påtaleberettiget:** {srv.beneficiary or '—'}")
    st.markdown(f"**Rådighed/tilstand:** {srv.disposition_type or '—'}")
    st.markdown(f"**Retlig type:** {srv.legal_type or '—'}")
    st.markdown(f"**Byggerelevant:** {'Ja' if srv.construction_relevance else 'Nej'}")
    st.markdown(f"**Anbefalet handling:** {srv.action_note or '—'}")
    st.markdown(f"**Scope-grundlag:** {srv.scope_basis or '—'}")

with col2:
    st.metric("Confidence", f"{srv.confidence:.2f}")
    st.caption(f"ID: {srv.servitut_id}")
    st.caption(f"Kilde-dokument: {srv.source_document}")

render_section("Evidenskæde", "Hver evidensblok viser excerpt, fuld chunk, OCR-tekst og original side.")

if srv.evidence:
    for ev in srv.evidence:
        with st.expander(f"Side {ev.page} | Chunk `{ev.chunk_id}`"):
            st.code(ev.text_excerpt, language="text")

            full_chunks = storage_service.load_chunks(case.case_id, ev.document_id)
            full_chunk = next((c for c in full_chunks if c.chunk_id == ev.chunk_id), None)
            if full_chunk:
                st.markdown("**Fuld chunk-tekst:**")
                st.code(full_chunk.text, language="text")

            pages = storage_service.load_ocr_pages(case.case_id, ev.document_id)
            page = next((p for p in pages if p.page_number == ev.page), None)
            if page:
                st.markdown(f"**OCR-tekst side {page.page_number}** (conf={page.confidence:.2f}):")
                st.code(page.text[:1500], language="text")

                # Render sidebillede on-demand fra original PDF
                pdf_path = storage_service.get_document_pdf_path(case.case_id, ev.document_id)
                if pdf_path.exists():
                    try:
                        import fitz
                        fitz_doc = fitz.open(str(pdf_path))
                        fitz_page = fitz_doc[ev.page - 1]
                        pix = fitz_page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                        st.image(pix.tobytes("png"), caption=f"Side {ev.page}")
                        fitz_doc.close()
                    except Exception:
                        pass
else:
    st.info("Ingen evidens-chunks registreret for denne servitut.")
