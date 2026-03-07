import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service

st.set_page_config(page_title="Inspicér chunks", layout="wide")
st.title("Inspicér chunks")

cases = case_service.list_cases()
if not cases:
    st.warning("Ingen cases.")
    st.stop()

case_options = {f"{c.name} ({c.case_id})": c.case_id for c in cases}
selected_label = st.selectbox("Vælg case", list(case_options.keys()))
case_id = case_options[selected_label]

docs = storage_service.list_documents(case_id)
if not docs:
    st.warning("Ingen dokumenter.")
    st.stop()

doc_options = {f"{d.filename} ({d.document_id})": d.document_id for d in docs}
selected_doc_label = st.selectbox("Vælg dokument", list(doc_options.keys()))
doc_id = doc_options[selected_doc_label]

chunks = storage_service.load_chunks(case_id, doc_id)
if not chunks:
    st.info("Ingen chunks for dette dokument. Kør OCR først.")
    st.stop()

page_filter = st.selectbox(
    "Filtrer på side",
    ["Alle"] + sorted(set(str(c.page) for c in chunks)),
)

filtered = chunks if page_filter == "Alle" else [c for c in chunks if str(c.page) == page_filter]
st.markdown(f"**{len(filtered)} chunks**")

for chunk in filtered:
    with st.expander(f"Chunk {chunk.chunk_index} | Side {chunk.page} | `{chunk.chunk_id}`"):
        st.text(chunk.text)
        st.caption(f"Chars: {chunk.char_start}–{chunk.char_end} | Doc: {chunk.document_id}")
