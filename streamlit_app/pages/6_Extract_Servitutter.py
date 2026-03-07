import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service
from app.services.extraction_service import extract_servitutter

st.set_page_config(page_title="Udtræk Servitutter", layout="wide")
st.title("Udtræk Servitutter")

cases = case_service.list_cases()
if not cases:
    st.warning("Ingen cases.")
    st.stop()

case_options = {f"{c.name} ({c.case_id})": c.case_id for c in cases}
selected_label = st.selectbox("Vælg case", list(case_options.keys()))
case_id = case_options[selected_label]

all_chunks = storage_service.load_all_chunks(case_id)
st.info(f"{len(all_chunks)} chunks i alt på tværs af dokumenter")

if st.button("Kør ekstraktion (Claude API)", type="primary"):
    if not all_chunks:
        st.error("Ingen chunks — kør OCR først.")
    else:
        with st.spinner("Kalder Claude API..."):
            try:
                servitutter = extract_servitutter(all_chunks, case_id)
                for srv in servitutter:
                    storage_service.save_servitut(srv)
                st.success(f"Udtrukket {len(servitutter)} servitutter")
            except Exception as e:
                st.error(f"Fejl: {e}")

st.divider()
st.subheader("Udtrukne servitutter")
servitutter = storage_service.list_servitutter(case_id)
if not servitutter:
    st.info("Ingen servitutter endnu.")
else:
    for srv in servitutter:
        conf_color = "green" if srv.confidence >= 0.8 else "orange" if srv.confidence >= 0.5 else "red"
        with st.expander(
            f"**{srv.title or 'Ukendt titel'}** | conf=:{conf_color}[{srv.confidence:.2f}]"
        ):
            col1, col2 = st.columns(2)
            col1.markdown(f"**Dato/ref:** {srv.date_reference or '—'}")
            col1.markdown(f"**Påtaleberettiget:** {srv.beneficiary or '—'}")
            col1.markdown(f"**Rådighed/tilstand:** {srv.disposition_type or '—'}")
            col2.markdown(f"**Retlig type:** {srv.legal_type or '—'}")
            col2.markdown(f"**Byggerelevant:** {'Ja' if srv.construction_relevance else 'Nej'}")
            col2.markdown(f"**Handling:** {srv.action_note or '—'}")
            st.markdown(f"**Resumé:** {srv.summary or '—'}")
            st.caption(f"ID: {srv.servitut_id} | Kilde: {srv.source_document}")
            if srv.evidence:
                st.markdown("**Evidens:**")
                for ev in srv.evidence:
                    st.text(f"[Side {ev.page}] {ev.text_excerpt[:200]}")
