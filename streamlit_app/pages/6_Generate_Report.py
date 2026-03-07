import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service
from app.services.report_service import generate_report

st.set_page_config(page_title="Generer Rapport", layout="wide")
st.title("Generer Servitutredegørelse")

cases = case_service.list_cases()
if not cases:
    st.warning("Ingen cases.")
    st.stop()

case_options = {f"{c.name} ({c.case_id})": c.case_id for c in cases}
selected_label = st.selectbox("Vælg case", list(case_options.keys()))
case_id = case_options[selected_label]

servitutter = storage_service.list_servitutter(case_id)
st.info(f"{len(servitutter)} servitutter klar til rapport")

if st.button("Generer rapport (Claude API)", type="primary"):
    if not servitutter:
        st.error("Ingen servitutter — kør ekstraktion først.")
    else:
        all_chunks = storage_service.load_all_chunks(case_id)
        with st.spinner("Genererer rapport..."):
            try:
                report = generate_report(servitutter, all_chunks, case_id)
                storage_service.save_report(report)
                st.success(f"Rapport genereret: `{report.report_id}`")
            except Exception as e:
                st.error(f"Fejl: {e}")

st.divider()
reports = storage_service.list_reports(case_id)
for report in reports:
    with st.expander(f"Rapport `{report.report_id}` — {report.created_at}"):
        if report.notes:
            st.markdown(f"**Bemærkninger:** {report.notes}")
        if report.markdown_content:
            st.markdown(report.markdown_content)
        else:
            for entry in report.servitutter:
                st.markdown(
                    f"**{entry.nr}.** {entry.description or '—'} "
                    f"| {entry.legal_type or '—'} | {entry.action or '—'}"
                )
