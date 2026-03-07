import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service

st.set_page_config(page_title="Review & Sporbarhed", layout="wide")
st.title("Review & Sporbarhed")
st.markdown("Klik på en servitut for at se tilhørende chunks og kilde-sider.")

cases = case_service.list_cases()
if not cases:
    st.warning("Ingen cases.")
    st.stop()

case_options = {f"{c.name} ({c.case_id})": c.case_id for c in cases}
selected_label = st.selectbox("Vælg case", list(case_options.keys()))
case_id = case_options[selected_label]

servitutter = storage_service.list_servitutter(case_id)
if not servitutter:
    st.info("Ingen servitutter. Kør ekstraktion først.")
    st.stop()

srv_options = {
    f"{srv.title or srv.servitut_id} (conf={srv.confidence:.2f})": srv.servitut_id
    for srv in servitutter
}
selected_srv_label = st.selectbox("Vælg servitut", list(srv_options.keys()))
srv_id = srv_options[selected_srv_label]

srv = storage_service.load_servitut(case_id, srv_id)
if not srv:
    st.error("Servitut ikke fundet.")
    st.stop()

col1, col2 = st.columns([2, 1])
with col1:
    st.subheader(srv.title or "Ukendt titel")
    st.markdown(f"**Resumé:** {srv.summary or '—'}")
    st.markdown(f"**Dato/ref:** {srv.date_reference or '—'}")
    st.markdown(f"**Påtaleberettiget:** {srv.beneficiary or '—'}")
    st.markdown(f"**Rådighed/tilstand:** {srv.disposition_type or '—'}")
    st.markdown(f"**Retlig type:** {srv.legal_type or '—'}")
    st.markdown(f"**Byggerelevant:** {'Ja' if srv.construction_relevance else 'Nej'}")
    st.markdown(f"**Anbefalet handling:** {srv.action_note or '—'}")

with col2:
    st.metric("Confidence", f"{srv.confidence:.2f}")
    st.caption(f"ID: {srv.servitut_id}")
    st.caption(f"Kilde: {srv.source_document}")

st.divider()
st.subheader("Evidens-chunks")
if srv.evidence:
    for ev in srv.evidence:
        with st.expander(f"Side {ev.page} | Chunk `{ev.chunk_id}`"):
            st.text(ev.text_excerpt)
            # Load full chunk for context
            full_chunks = storage_service.load_chunks(case_id, ev.document_id)
            full_chunk = next((c for c in full_chunks if c.chunk_id == ev.chunk_id), None)
            if full_chunk:
                st.markdown("**Fuld chunk-tekst:**")
                st.text(full_chunk.text)
            # Show page context
            doc = storage_service.load_document(case_id, ev.document_id)
            if doc and doc.pages:
                page = next((p for p in doc.pages if p.page_number == ev.page), None)
                if page:
                    st.markdown(f"**Kilde-side {page.page_number}** ({page.extraction_method}):")
                    st.text(page.text[:1500])
else:
    st.info("Ingen evidens-chunks registreret for denne servitut.")
