import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.db.database import get_session_ctx
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


with get_session_ctx() as session:
    servitutter = matrikel_service.filter_servitutter_for_target(
        storage_service.list_servitutter(session, case.case_id),
        [case.target_matrikel] if case.target_matrikel else [],
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

with get_session_ctx() as session:
    srv = storage_service.load_servitut(session, case.case_id, srv_id)
if not srv:
    st.error("Servitut ikke fundet.")
    st.stop()

render_section("Servitutprofil", "Sammenfatning af det valgte fund før dyk ned i evidenskæden.")

st.subheader(srv.title or "Ukendt titel")

# Resumé som info-boks
if srv.summary:
    st.info(srv.summary)

# Nøglemålinger — første række
m_col1, m_col2, m_col3 = st.columns(3)
m_col1.metric("Dato / løbenummer", srv.date_reference or "—")
target_label = "Ja" if srv.applies_to_target_matrikel is True else ("Nej" if srv.applies_to_target_matrikel is False else "Uafklaret")
m_col2.metric("Gælder målmatrikel", target_label)
m_col3.metric("Confidence", f"{srv.confidence:.0%}")

st.divider()

# Juridisk blok — to kolonner
j_col1, j_col2 = st.columns(2)
j_col1.markdown(f"**Påtaleberettiget**\n\n{srv.beneficiary or '—'}")
j_col1.markdown(f"**Rådighed / tilstand**\n\n{srv.disposition_type or '—'}")
j_col2.markdown(f"**Retlig type**\n\n{srv.legal_type or '—'}")
j_col2.markdown(f"**Anbefalet handling**\n\n{srv.action_note or '—'}")

st.divider()

# Byggerelevans og scope
MARKERING_BADGE = {
    "rød": "🔴 Rød — direkte byggerelevans",
    "orange": "🟠 Orange — kræver stillingtagen",
    "sort": "⚫ Sort — ingen byggerelevans",
}
markering_text = MARKERING_BADGE.get(srv.byggeri_markering or "", "— Ikke vurderet")
b_col1, b_col2 = st.columns(2)
b_col1.markdown(f"**Byggemarkering**\n\n{markering_text}")
if srv.applies_to_matrikler:
    b_col2.markdown(f"**Gælder matrikler**\n\n{', '.join(srv.applies_to_matrikler)}")
if srv.scope_basis:
    st.caption(f"Scope-grundlag: {srv.scope_basis}")

st.caption(f"ID: {srv.servitut_id} · Kilde: {srv.source_document}")

render_section("Evidenskæde", "Hver evidensblok viser excerpt, fuld chunk, OCR-tekst og original side.")

if srv.evidence:
    for ev in srv.evidence:
        with st.expander(f"Side {ev.page} | Chunk `{ev.chunk_id}`"):
            st.code(ev.text_excerpt, language="text")

            with get_session_ctx() as session:
                full_chunks = storage_service.load_chunks(session, case.case_id, ev.document_id)
            full_chunk = next((c for c in full_chunks if c.chunk_id == ev.chunk_id), None)
            if full_chunk:
                st.markdown("**Fuld chunk-tekst:**")
                st.code(full_chunk.text, language="text")

            with get_session_ctx() as session:
                pages = storage_service.load_ocr_pages(session, case.case_id, ev.document_id)
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
