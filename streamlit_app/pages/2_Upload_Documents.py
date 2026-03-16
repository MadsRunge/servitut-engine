import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import storage_service
from app.services.case_service import remove_document_from_case
from app.services.document_service import create_document_from_bytes
from streamlit_app.ui import (
    parse_status_label,
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_section,
    select_case,
    setup_page,
)

setup_page(
    "Upload dokumenter",
    "Tilføj PDF-akter til en sag. Upload tinglysningsattesten separat — den bruges som autoritativ kildeliste.",
    step="upload",
)

case = select_case()
render_case_banner(case)
render_case_stats(case.case_id)


def _save_uploaded_file(uploaded_file, case_id: str, document_type: str) -> str:
    doc = create_document_from_bytes(
        file_bytes=uploaded_file.getvalue(),
        filename=uploaded_file.name,
        case_id=case_id,
        document_type=document_type,
    )
    return doc.document_id


# --- Tinglysningsattest ---
render_section(
    "Tinglysningsattest",
    "Upload tinglysningsattesten for ejendommen. Den bruges som autoritativ liste over hvilke servitutter der eksisterer.",
)

existing_docs = storage_service.list_documents(case.case_id)
existing_attest = [d for d in existing_docs if d.document_type == "tinglysningsattest"]

if existing_attest:
    st.info(f"Tinglysningsattest allerede uploadet: **{existing_attest[0].filename}** (`{existing_attest[0].document_id}`)")
    with st.expander("🔄 Upload ny version"):
        attest_file = st.file_uploader("Upload tinglysningsattest (PDF)", type=["pdf"], key="attest_upload")
        if attest_file and st.button("Upload ny tinglysningsattest", key="attest_btn"):
            doc_id = _save_uploaded_file(attest_file, case.case_id, "tinglysningsattest")
            st.success(f"Uploadet: **{attest_file.name}** (`{doc_id}`)")
            st.rerun()
else:
    attest_file = st.file_uploader("Upload tinglysningsattest (PDF)", type=["pdf"], key="attest_upload")
    if attest_file and st.button("Upload tinglysningsattest", key="attest_btn", type="primary"):
        doc_id = _save_uploaded_file(attest_file, case.case_id, "tinglysningsattest")
        st.success(f"Uploadet: **{attest_file.name}** (`{doc_id}`)")
        st.rerun()

# --- Akter ---
render_section(
    "Akter",
    "Upload de individuelle akt-PDFer. Disse bruges til at berige servitutterne med fulde detaljer.",
)
st.page_link(
    "pages/2a_Split_PDF.py",
    label="→ Opdel en stor PDF først",
    icon="✂️",
)

akt_files = st.file_uploader(
    "Upload akter (PDF)", type=["pdf"], accept_multiple_files=True, key="akt_upload"
)

if akt_files and st.button("Upload valgte akter", key="akt_btn"):
    for uploaded_file in akt_files:
        doc_id = _save_uploaded_file(uploaded_file, case.case_id, "akt")
        st.success(f"Uploadet: **{uploaded_file.name}** (`{doc_id}`)")
    st.rerun()

# --- Dokumentbibliotek ---
render_section("Dokumentbibliotek", "Oversigt over filer i den aktive sag og deres aktuelle pipeline-status.")
docs = storage_service.list_documents(case.case_id)
if docs:
    for doc in docs:
        is_attest = doc.document_type == "tinglysningsattest"
        type_badge = "📋 Tinglysningsattest" if is_attest else "📄 Akt"
        col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 0.5])
        col1.markdown(f"**{doc.filename}**  \n`{doc.document_id}`")
        col2.caption(type_badge)
        col3.metric("Status", parse_status_label(doc.parse_status))
        col4.metric("Sider", str(doc.page_count))
        if col5.button("🗑", key=f"del_{doc.document_id}", help="Slet dokument"):
            remove_document_from_case(case.case_id, doc.document_id)
            st.toast(f"{doc.filename} slettet")
            st.rerun()
else:
    render_empty_state("Ingen dokumenter endnu", "Upload tinglysningsattest og akter for at fortsætte til OCR.")
