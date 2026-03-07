import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service

st.set_page_config(page_title="Inspicér sider", layout="wide")
st.title("Inspicér OCR-sider")
st.caption("Se sidebilleder og transskriberet tekst side om side")

cases = case_service.list_cases()
if not cases:
    st.warning("Ingen cases.")
    st.stop()

case_options = {f"{c.name} ({c.case_id})": c.case_id for c in cases}
selected_label = st.selectbox("Vælg case", list(case_options.keys()))
case_id = case_options[selected_label]

docs = storage_service.list_documents(case_id)
ocr_docs = [d for d in docs if d.parse_status == "ocr_done"]
if not ocr_docs:
    st.info("Ingen dokumenter med OCR endnu. Kør OCR under trin 3.")
    st.stop()

doc_options = {f"{d.filename} ({d.document_id})": d.document_id for d in ocr_docs}
selected_doc_label = st.selectbox("Vælg dokument", list(doc_options.keys()))
doc_id = doc_options[selected_doc_label]

pages = storage_service.load_ocr_pages(case_id, doc_id)
if not pages:
    st.warning("Ingen OCR-data fundet.")
    st.stop()

st.info(f"{len(pages)} sider i dette dokument")

for page in pages:
    with st.expander(f"Side {page.page_number} — {len(page.text)} tegn — conf={page.confidence:.1f}"):
        col_img, col_txt = st.columns(2)

        with col_img:
            st.caption("Sidebillede")
            if page.image_path and Path(page.image_path).exists():
                st.image(page.image_path)
            else:
                st.info("Intet billede gemt.")

        with col_txt:
            st.caption("OCR-tekst (Claude Vision)")
            if page.text:
                st.text_area(
                    label="",
                    value=page.text,
                    height=400,
                    key=f"ocr_text_{doc_id}_{page.page_number}",
                )
            else:
                st.warning("Ingen tekst udtrukket fra denne side.")
