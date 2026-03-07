import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.models.document import Document
from app.services import case_service, storage_service
from app.utils.ids import generate_doc_id

st.set_page_config(page_title="Upload dokumenter", layout="wide")
st.title("Upload PDF-dokumenter")

cases = case_service.list_cases()
if not cases:
    st.warning("Ingen cases. Opret en case først.")
    st.stop()

case_options = {f"{c.name} ({c.case_id})": c.case_id for c in cases}
selected_label = st.selectbox("Vælg case", list(case_options.keys()))
case_id = case_options[selected_label]

uploaded_files = st.file_uploader(
    "Upload PDF-filer", type=["pdf"], accept_multiple_files=True
)

if uploaded_files and st.button("Upload valgte filer"):
    for uploaded_file in uploaded_files:
        doc_id = generate_doc_id()
        pdf_path = storage_service.get_document_pdf_path(case_id, doc_id)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        with open(pdf_path, "wb") as f:
            shutil.copyfileobj(uploaded_file, f)

        doc = Document(
            document_id=doc_id,
            case_id=case_id,
            filename=uploaded_file.name,
            file_path=str(pdf_path),
            parse_status="pending",
        )
        storage_service.save_document(doc)
        case_service.add_document_to_case(case_id, doc_id)
        st.success(f"Uploadet: **{uploaded_file.name}** (`{doc_id}`)")

st.divider()
st.subheader("Eksisterende dokumenter")
docs = storage_service.list_documents(case_id)
if docs:
    for doc in docs:
        st.markdown(f"- `{doc.document_id}` **{doc.filename}** — status: `{doc.parse_status}`")
else:
    st.info("Ingen dokumenter uploadet endnu.")
