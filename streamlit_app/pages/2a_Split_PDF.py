import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services.document_service import create_document_from_bytes
from app.services.pdf_service import (
    build_split_suggestion,
    get_pdf_page_count,
    parse_page_ranges,
    split_pdf_bytes,
)
from streamlit_app.ui import (
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_section,
    select_case,
    setup_page,
)


def _sync_split_defaults(case_id: str, filename: str, pdf_size: int, total_pages: int) -> None:
    signature = f"{case_id}:{filename}:{pdf_size}:{total_pages}"
    if st.session_state.get("split_pdf_signature") == signature:
        return

    suggested_pages_per_part = min(100, total_pages)
    st.session_state["split_pdf_signature"] = signature
    st.session_state["split_pages_per_part"] = suggested_pages_per_part
    st.session_state["split_ranges_text"] = build_split_suggestion(
        total_pages=total_pages,
        pages_per_part=suggested_pages_per_part,
    )


def _render_split_status(total_pages: int) -> None:
    try:
        ranges = parse_page_ranges(st.session_state.get("split_ranges_text", ""), total_pages)
    except ValueError as exc:
        st.caption(str(exc))
        return

    covered_pages = sum(page_range.end_page - page_range.start_page + 1 for page_range in ranges)
    st.caption(f"{len(ranges)} del-PDF'er dækker {covered_pages} af {total_pages} sider.")
    if covered_pages < total_pages:
        st.warning(
            f"{total_pages - covered_pages} sider er ikke valgt og bliver ikke uploadet som egne dokumenter.",
            icon="⚠️",
        )


setup_page(
    "Opdel PDF",
    "Opdel en stor akt-PDF i mindre filer, før de gemmes som dokumenter i sagen.",
    step="split",
)

case = select_case()
render_case_banner(case)
render_case_stats(case.case_id)

render_section(
    "Stor akt-PDF",
    "Upload én stor PDF, angiv sideintervaller, og gem delene som separate akt-dokumenter klar til OCR.",
)

split_file = st.file_uploader("Upload stor akt-PDF", type=["pdf"], key="split_akt_upload")

if not split_file:
    render_empty_state(
        "Ingen PDF valgt",
        "Vælg en stor akt-PDF for at opdele den i mindre dokumenter før OCR.",
    )
    st.page_link("pages/2_Upload_Documents.py", label="→ Gå til almindelig upload", icon="📎")
    st.stop()

split_bytes = split_file.getvalue()

try:
    total_pages = get_pdf_page_count(split_bytes)
except Exception as exc:
    st.error(f"Kunne ikke læse PDF'en: {exc}")
    st.stop()

_sync_split_defaults(case.case_id, split_file.name, len(split_bytes), total_pages)

st.info(
    f"`{split_file.name}` indeholder {total_pages} sider. "
    "Opdel den i mindre dele, så OCR ikke skal køre på hele dokumentet på én gang."
)

summary_col1, summary_col2 = st.columns(2)
summary_col1.metric("Sider i PDF", str(total_pages))
summary_col2.number_input(
    "Sider pr. del",
    min_value=1,
    max_value=total_pages,
    step=1,
    key="split_pages_per_part",
)

actions_col1, actions_col2 = st.columns([2, 2])
if actions_col1.button("Generér standardintervaller", key="split_generate_ranges", width="stretch"):
    st.session_state["split_ranges_text"] = build_split_suggestion(
        total_pages=total_pages,
        pages_per_part=int(st.session_state["split_pages_per_part"]),
    )
with actions_col2:
    st.page_link("pages/2_Upload_Documents.py", label="Almindelig upload", icon="📎")

st.text_area(
    "Sideintervaller",
    key="split_ranges_text",
    height=220,
    help="Én del pr. linje. Format: `1-80 | Del 1` eller `81-160`. Etiketten efter `|` er valgfri.",
)
_render_split_status(total_pages)

if st.button("Opdel og gem som akter", key="split_upload_btn", type="primary", width="stretch"):
    try:
        ranges = parse_page_ranges(st.session_state.get("split_ranges_text", ""), total_pages)
        split_parts = split_pdf_bytes(split_bytes, ranges, split_file.name)
    except ValueError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Opdeling fejlede: {exc}")
    else:
        for part_filename, part_bytes in split_parts:
            doc = create_document_from_bytes(case.case_id, part_filename, part_bytes, "akt")
            st.success(f"Uploadet: **{part_filename}** (`{doc.document_id}`)")
        st.rerun()
