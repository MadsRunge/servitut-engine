import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service
from app.services.report_service import generate_report
from streamlit_app.ui import (
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_section,
    select_case,
    setup_page,
)

setup_page(
    "Generer redegørelse",
    "Saml de udtrukne servitutter i en læsbar rapport med sporbarhed til chunks og OCR-tekst.",
    step="report",
)

case = select_case()
render_case_banner(case)
render_case_stats(case.case_id)

servitutter = storage_service.list_servitutter(case.case_id)
render_section("Rapportgrundlag", f"{len(servitutter)} servitut(ter) er klar til rapportgenerering.")

if st.button("Generer rapport", type="primary"):
    if not servitutter:
        st.error("Ingen servitutter — kør ekstraktion først.")
    else:
        all_chunks = storage_service.load_all_chunks(case.case_id)
        with st.spinner("Genererer rapport..."):
            try:
                report = generate_report(servitutter, all_chunks, case.case_id)
                storage_service.save_report(report)
                st.success(f"Rapport genereret: `{report.report_id}`")
                st.rerun()
            except Exception as e:
                st.error(f"Fejl: {e}")

render_section("Gemte rapporter", "Tidligere redegørelser for den aktive sag.")
reports = storage_service.list_reports(case.case_id)
if not reports:
    render_empty_state("Ingen rapporter endnu", "Generér den første redegørelse, når servitutterne er gennemgået.")
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
