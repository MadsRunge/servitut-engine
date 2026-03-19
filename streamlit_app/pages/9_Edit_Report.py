import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import storage_service
from app.services.report_editor_service import report_to_editor_rows, update_report_from_editor
from streamlit_app.ui import (
    render_case_banner,
    render_empty_state,
    select_case,
    setup_page,
)


def _select_report(case_id: str):
    reports = sorted(
        storage_service.list_reports(case_id),
        key=lambda r: r.created_at,
        reverse=True,
    )
    if not reports:
        render_empty_state("Ingen rapporter", "Generér først en redegørelse, før den kan redigeres.")
        st.page_link("pages/8_Generate_Report.py", label="→ Gå til rapportgenerering", icon="📄")
        st.stop()

    report_labels = {
        (
            f"{r.report_id} · {r.created_at:%Y-%m-%d %H:%M}"
            + (" · manuelt redigeret" if r.manually_edited else "")
        ): r.report_id
        for r in reports
    }
    labels = list(report_labels.keys())
    selected_label = st.selectbox("Vælg rapport", labels, label_visibility="collapsed")
    selected_report_id = report_labels[selected_label]
    return next(r for r in reports if r.report_id == selected_report_id)


setup_page(
    "Redigér redegørelse",
    "Gennemgå og ret rapporttabellen, før den eksporteres som endeligt produkt.",
    step="edit",
)

case = select_case()
render_case_banner(case)

st.divider()

report = _select_report(case.case_id)

# Kompakt metadata-linje
status_badge = "✏️ Manuelt redigeret" if report.manually_edited else "🤖 LLM-genereret"
meta_parts = [
    f"`{report.report_id}`",
    f"**{len(report.servitutter)} poster**",
    status_badge,
    f"Oprettet {report.created_at:%Y-%m-%d %H:%M}",
]
if report.edited_at:
    meta_parts.append(f"· Sidst redigeret {report.edited_at:%Y-%m-%d %H:%M}")
st.caption(" · ".join(meta_parts))

# Bemærkninger
notes_key = f"report_notes_{report.report_id}"
notes_value = st.text_area(
    "Bemærkninger",
    value=report.notes or "",
    key=notes_key,
    height=72,
    placeholder="Tilføj eventuelle noter eller forbehold til rapporten...",
    label_visibility="collapsed",
)

st.divider()

# --- Redigeringsvindue ---
editor_rows = report_to_editor_rows(report)

edited_rows = st.data_editor(
    editor_rows,
    width="stretch",
    hide_index=True,
    num_rows="fixed",
    disabled=["servitut_id"],
    height=580,
    column_config={
        "nr": st.column_config.NumberColumn(
            "Prioritet",
            min_value=1,
            step=1,
            help="Rækker sorteres efter dette felt ved gem.",
            width="small",
        ),
        "date_reference": st.column_config.TextColumn("Dato / løbenr.", width="small"),
        "title": st.column_config.TextColumn("Titel", width="medium"),
        "byggeri_markering": st.column_config.SelectboxColumn(
            "Byggeri",
            options=["", "rød", "orange", "sort"],
            width="small",
            help="rød = direkte byggerelevans · orange = skal vurderes · sort = ingen byggerelevans",
        ),
        "raw_text": st.column_config.TextColumn("Servituttens tekst", width="large"),
        "description": st.column_config.TextColumn("Servituttens indhold", width="large"),
        "beneficiary": st.column_config.TextColumn("Påtaleberettiget", width="medium"),
        "disposition": st.column_config.SelectboxColumn(
            "Rådighed / tilstand",
            options=["", "Rådighed", "Tilstand"],
            width="medium",
            help="Rådighed = rådighedsservitut (positiv) · Tilstand = tilstandsservitut (negativ)",
        ),
        "legal_type": st.column_config.SelectboxColumn(
            "Offentlig / privatretlig",
            options=["", "Offentligretlig", "Privatretlig"],
            width="medium",
        ),
        "action": st.column_config.TextColumn("Håndtering / handling", width="medium"),
        "scope": st.column_config.SelectboxColumn(
            "Vedrører projekt",
            options=["", "Ja", "Måske", "Nej"],
            width="small",
        ),
        "scope_detail": st.column_config.TextColumn("Scope-detalje", width="medium"),
        "relevant_for_project": st.column_config.CheckboxColumn("Projektkritisk"),
        "beneficiary_amt_warning": st.column_config.CheckboxColumn(
            "Amt-advarsel",
            help="Automatisk markeret hvis påtaleberettiget indeholder 'amt'. Fjern markeringen efter gennemgang.",
        ),
        "servitut_id": st.column_config.TextColumn("Servitut-id", width="medium"),
    },
)

try:
    draft_report = update_report_from_editor(
        report.model_copy(deep=True),
        edited_rows,
        notes=notes_value,
    )
except Exception as exc:
    st.error(f"Kunne ikke bygge redigeret rapport: {exc}")
    st.stop()

st.divider()

save_col, nav_col = st.columns([3, 2])
with save_col:
    if st.button("Gem ændringer", type="primary", width="stretch"):
        saved_report = update_report_from_editor(report, edited_rows, notes=notes_value)
        storage_service.save_report(saved_report)
        st.toast("Rapport gemt.", icon="✅")
        st.rerun()
with nav_col:
    st.page_link("pages/10_Review.py", label="Gå til review og sporbarhed →", icon="🔎")
