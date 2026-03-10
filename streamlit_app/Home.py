import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app.services.case_service import list_cases
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

cases = list_cases()

if not cases:
    render_empty_state(
        "Ingen sager endnu",
        "Start med at oprette en ny sag i trin 1. Derefter kan du uploade PDF’er og køre den fulde OCR-pipeline.",
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
                st.page_link("pages/2_Upload_Documents.py", label="→ Upload dokumenter", icon="📎")
            elif stats.chunks == 0:
                st.page_link("pages/3_Run_OCR.py", label="→ Kør OCR", icon="🔍")
            elif stats.servitutter == 0:
                st.page_link("pages/6_Extract_Servitutter.py", label="→ Udtræk servitutter", icon="⚙️")
            elif stats.reports == 0:
                st.page_link("pages/7_Generate_Report.py", label="→ Generer redegørelse", icon="📄")
            else:
                st.page_link("pages/8_Review.py", label="→ Review og sporbarhed", icon="🔎")
            st.caption(
                f"{case.case_id} · oprettet {case.created_at:%Y-%m-%d %H:%M} · "
                f"status {stats.case_status}"
            )
