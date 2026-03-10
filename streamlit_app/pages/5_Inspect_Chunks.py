import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service
from app.utils.text import has_servitut_keywords
from streamlit_app.ui import (
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_section,
    select_case,
    select_document,
    setup_page,
)

setup_page(
    "Inspicér chunks",
    "Kontrollér chunk-størrelse, sidesporing og tekstfordeling før den strukturerede ekstraktion kaldes.",
    step="chunks",
)

case = select_case()
render_case_banner(case)
render_case_stats(case.case_id)

docs = storage_service.list_documents(case.case_id)
if not docs:
    render_empty_state("Ingen dokumenter", "Upload dokumenter og kør OCR før chunk-inspektion.")
    st.stop()

render_section("Dokument og filtrering", "Brug sidefilter til hurtig kontrol af enkelte sider.")
doc = select_document(case.case_id, docs)
chunks = storage_service.load_chunks(case.case_id, doc.document_id)
if not chunks:
    render_empty_state("Ingen chunks endnu", "Kør OCR for dokumentet først.")
    st.stop()

col_filter1, col_filter2 = st.columns([2, 1])
page_filter = col_filter1.selectbox(
    "Filtrer på side",
    ["Alle"] + sorted(set(str(c.page) for c in chunks)),
)
only_relevant = col_filter2.toggle("Kun servitut-relevante", value=False)

filtered = chunks if page_filter == "Alle" else [c for c in chunks if str(c.page) == page_filter]
if only_relevant:
    filtered = [c for c in filtered if has_servitut_keywords(c.text)]

render_section("Chunk-liste", f"{len(filtered)} chunk(s) matcher det aktive filter.")

for chunk in filtered:
    relevant = has_servitut_keywords(chunk.text)
    relevans_icon = "✅" if relevant else "—"
    with st.expander(f"{relevans_icon} Chunk {chunk.chunk_index} | Side {chunk.page} | `{chunk.chunk_id}`"):
        st.caption(f"Servitut-relevant: {'Ja — indeholder nøgleord' if relevant else 'Nej'}")
        st.code(chunk.text, language="text")
        st.caption(f"Chars: {chunk.char_start}–{chunk.char_end} | Doc: {chunk.document_id}")
