import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services.case_service import create_case

st.set_page_config(page_title="Opret Case", layout="centered")
st.title("Opret ny case")

with st.form("create_case_form"):
    name = st.text_input("Sagsnavn *", placeholder="fx 'Matr. 5a, Lyngby'")
    address = st.text_input("Adresse", placeholder="fx 'Lyngby Hovedgade 1, 2800 Kongens Lyngby'")
    external_ref = st.text_input("Ekstern reference", placeholder="fx sagsnummer fra eget system")
    submitted = st.form_submit_button("Opret case")

if submitted:
    if not name:
        st.error("Sagsnavn er påkrævet.")
    else:
        case = create_case(name, address or None, external_ref or None)
        st.success(f"Case oprettet: **{case.name}** (`{case.case_id}`)")
        st.json(case.model_dump(mode="json"))
