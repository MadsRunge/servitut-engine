import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app.db.database import get_session_ctx
from app.services.case_service import delete_case, list_cases
from streamlit_app.ui import (
    compute_case_stats,
    render_case_banner,
    render_empty_state,
    render_section,
    render_stat_cards,
    setup_page,
)

setup_page(
    "Servitut Engine",
    "Ét samlet arbejdsrum til OCR, struktureret udtræk og redegørelser for servitutter.",
    step="home",
)

with get_session_ctx() as _session:
    cases = list_cases(_session)

if not cases:
    render_empty_state(
        "Ingen sager endnu",
        "Start med at oprette en ny sag i trin 1. Derefter kan du opdele store PDF’er eller uploade dokumenter og køre den fulde OCR-pipeline.",
    )
else:
    total_docs = 0
    total_servitutter = 0
    total_reports = 0
    for case in cases:
        stats = compute_case_stats(case.case_id)
        total_docs += stats.documents
        total_servitutter += stats.servitutter
        total_reports += stats.reports

    render_stat_cards(
        [
            ("Sager", str(len(cases)), "Aktive sager i workspace"),
            ("Dokumenter", str(total_docs), "Uploadede PDF-akter"),
            ("Servitutter", str(total_servitutter), "Gemte udtræk"),
            ("Rapporter", str(total_reports), "Producerede redegørelser"),
        ]
    )
    render_section("Sagsoversigt", "Hver sag viser pipeline-modenhed og aktuelle artefakter.")
    for case in cases:
        stats = compute_case_stats(case.case_id)
        with st.container(border=False):
            st.markdown(f"### {case.name}")
            render_case_banner(case)
            render_stat_cards(
                [
                    ("Dokumenter", str(stats.documents), f"{stats.ocr_ready} OCR-klare"),
                    ("Sider", str(stats.pages), "OCR-tekstsider"),
                    ("Chunks", str(stats.chunks), "Klar til LLM"),
                    ("Servitutter", str(stats.servitutter), "Registrerede fund"),
                    ("Rapporter", str(stats.reports), "Genererede rapporter"),
                ]
            )
            # Næste-trin link baseret på pipeline-modenhed
            if stats.documents == 0:
                st.page_link("pages/2a_Split_PDF.py", label="→ Opdel stor PDF eller upload dokumenter", icon="✂️")
            elif stats.chunks == 0:
                st.page_link("pages/3_Run_OCR.py", label="→ Kør OCR", icon="🔍")
            elif stats.servitutter == 0:
                st.page_link("pages/6_Filter_Chunks.py", label="→ Filtrer chunks", icon="🔬")
            elif stats.reports == 0:
                st.page_link("pages/8_Generate_Report.py", label="→ Generer redegørelse", icon="📄")
            else:
                st.page_link("pages/9_Edit_Report.py", label="→ Redigér redegørelse", icon="✍️")
            st.caption(
                f"{case.case_id} · oprettet {case.created_at:%Y-%m-%d %H:%M} · "
                f"status {stats.case_status}"
            )

            confirm_key = f"delete_confirm_{case.case_id}"
            if st.session_state.get(confirm_key):
                st.error(
                    f"**Advarsel:** Dette sletter al data for sagen **{case.name}** permanent — "
                    f"dokumenter, OCR-sider, chunks, servitutter og rapporter. Handlingen kan ikke fortrydes."
                )
                col_yes, col_no, _ = st.columns([1, 1, 4])
                if col_yes.button("Ja, slet alt data", key=f"delete_yes_{case.case_id}", type="primary"):
                    with get_session_ctx() as _s:
                        delete_case(_s, case.case_id)
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
                if col_no.button("Annuller", key=f"delete_no_{case.case_id}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
            else:
                if st.button("Slet sag", key=f"delete_btn_{case.case_id}"):
                    st.session_state[confirm_key] = True
                    st.rerun()
