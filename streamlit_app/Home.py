import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app.services.case_service import list_cases

st.set_page_config(page_title="Servitut Engine", layout="wide")
st.title("Servitut Engine v1")
st.markdown("Pipeline: PDF → ocrmypdf → OCR-tekst → Chunks → Servitutter → Redegørelse")

cases = list_cases()

if not cases:
    st.info("Ingen cases endnu. Opret en case under **Create Case**.")
else:
    st.subheader(f"{len(cases)} case(s)")
    for case in cases:
        with st.expander(f"**{case.name}** — `{case.case_id}`"):
            col1, col2, col3 = st.columns(3)
            col1.metric("Status", case.status)
            col2.metric("Dokumenter", len(case.document_ids))
            col3.write(f"**Adresse:** {case.address or '—'}")
            st.caption(f"Oprettet: {case.created_at} | Ref: {case.external_ref or '—'}")

st.divider()
st.markdown(
    "**Pipeline-trin:** "
    "[1 Create Case](#) → [2 Upload](#) → [3 OCR](#) → [4 Inspect Pages](#) → [5 Chunks](#) → [6 Extract](#) → [7 Report](#) → [8 Review](#)"
)
