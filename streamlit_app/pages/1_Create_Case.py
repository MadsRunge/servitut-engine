import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.db.database import get_session_ctx
from app.services.case_service import create_case
from streamlit_app.ui import render_section, setup_page

setup_page(
    "Opret ny sag",
    "Registrer sagen først. Adresse og ekstern reference gør senere review og sporbarhed langt mere overskuelig.",
    step="create",
    layout="centered",
)
render_section("Sagsmetadata", "Gem kun den metadata, der faktisk hjælper den videre analyse.")

with st.form("create_case_form"):
    name = st.text_input("Sagsnavn *", placeholder="fx 'Matr. 5a, Lyngby'")
    address = st.text_input("Adresse", placeholder="fx 'Lyngby Hovedgade 1, 2800 Kongens Lyngby'")
    external_ref = st.text_input("Ekstern reference", placeholder="fx sagsnummer fra eget system")
    submitted = st.form_submit_button("Opret sag", type="primary")

if submitted:
    if not name:
        st.error("Sagsnavn er påkrævet.")
    else:
        with get_session_ctx() as _s:
            case = create_case(_s, name, address or None, external_ref or None)
        st.success(f"Sag oprettet: **{case.name}** (`{case.case_id}`)")
        col1, col2 = st.columns(2)
        col1.metric("Status", case.status)
        col2.metric("Dokumenter", str(len(case.document_ids)))
        st.page_link("pages/2_Upload_Documents.py", label="Fortsæt til upload →", icon="📎")
