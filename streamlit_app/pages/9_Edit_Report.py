import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import storage_service
from app.services.report_editor_service import report_to_editor_rows, update_report_from_editor
from app.services.report_render_service import build_html_report, build_markdown_report
from streamlit_app.ui import (
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_report_entry_card,
    render_section,
    select_case,
    setup_page,
)


def _select_report(case_id: str):
    reports = sorted(
        storage_service.list_reports(case_id),
        key=lambda report: report.created_at,
        reverse=True,
    )
    if not reports:
        render_empty_state("Ingen rapporter", "Generér først en redegørelse, før den kan redigeres.")
        st.page_link("pages/8_Generate_Report.py", label="→ Gå til rapportgenerering", icon="📄")
        st.stop()

    report_labels = {
        (
            f"{report.report_id} · {report.created_at:%Y-%m-%d %H:%M}"
            + (" · manuelt redigeret" if report.manually_edited else "")
        ): report.report_id
        for report in reports
    }
    labels = list(report_labels.keys())
    selected_label = st.selectbox("Vælg rapport", labels)
    selected_report_id = report_labels[selected_label]
    return next(report for report in reports if report.report_id == selected_report_id)


def _build_base_name(case_name: str, report) -> str:
    matrikel_slug = "-".join(report.target_matrikler) if report.target_matrikler else "ukendt"
    date_slug = report.created_at.strftime("%Y-%m-%d")
    case_slug = case_name.replace(" ", "_").replace("/", "-")[:40]
    return f"servitutredegoerelse_{case_slug}_{matrikel_slug}_{date_slug}"


setup_page(
    "Redigér redegørelse",
    "Gennemgå og ret rapporttabellen, før den eksporteres som endeligt produkt.",
    step="edit",
)

case = select_case()
render_case_banner(case)
render_case_stats(case.case_id)

report = _select_report(case.case_id)

render_section(
    "Redigeringsvindue",
    "Hele rapporttabellen kan redigeres her. Ændringer gemmes tilbage på rapporten og bruges i eksportfilerne.",
)

stats_col1, stats_col2, stats_col3 = st.columns(3)
stats_col1.metric("Rapport-id", report.report_id)
stats_col2.metric("Poster", str(len(report.servitutter)))
stats_col3.metric("Status", "Manuelt redigeret" if report.manually_edited else "LLM-genereret")
st.caption(
    f"Oprettet: {report.created_at:%Y-%m-%d %H:%M}"
    + (f" · Sidst redigeret: {report.edited_at:%Y-%m-%d %H:%M}" if report.edited_at else "")
)

editor_rows = report_to_editor_rows(report)
notes_key = f"report_notes_{report.report_id}"
notes_value = st.text_area(
    "Bemærkninger",
    value=report.notes or "",
    key=notes_key,
    height=120,
)

edited_rows = st.data_editor(
    editor_rows,
    width="stretch",
    hide_index=True,
    num_rows="fixed",
    disabled=["servitut_id"],
    column_config={
        "nr": st.column_config.NumberColumn("Prioritet", min_value=1, step=1, help="Rækker sorteres efter dette felt ved gem."),
        "date_reference": st.column_config.TextColumn("Dato / løbenr.", width="small"),
        "raw_text": st.column_config.TextColumn("Servituttens tekst", width="large"),
        "description": st.column_config.TextColumn("Servituttens indhold", width="large"),
        "beneficiary": st.column_config.TextColumn("Påtaleberettiget", width="medium"),
        "disposition": st.column_config.TextColumn("Rådighed / tilstand", width="medium"),
        "legal_type": st.column_config.TextColumn("Offentlig / privatretlig", width="medium"),
        "action": st.column_config.TextColumn("Håndtering / handling", width="medium"),
        "scope": st.column_config.SelectboxColumn("Vedrører projekt", options=["", "Ja", "Måske", "Nej"], width="small"),
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

save_col1, save_col2 = st.columns([2, 2])
if save_col1.button("Gem ændringer på rapporten", type="primary", width="stretch"):
    saved_report = update_report_from_editor(report, edited_rows, notes=notes_value)
    storage_service.save_report(saved_report)
    st.success(f"Rapport `{saved_report.report_id}` gemt med manuelle rettelser.")
    st.rerun()
with save_col2:
    st.page_link("pages/10_Review.py", label="Gå til review og sporbarhed", icon="🔎")

render_section("Eksport", "Eksporten nedenfor afspejler den aktuelle redigerede tabel.")

markdown_export = build_markdown_report(draft_report)
html_export = build_html_report(draft_report, case)
json_export = json.dumps(
    draft_report.model_dump(mode="json"),
    ensure_ascii=False,
    indent=2,
)
base_name = _build_base_name(case.name, draft_report)

export_col1, export_col2, export_col3 = st.columns(3)
export_col1.download_button(
    "Download rapport (.md)",
    data=markdown_export,
    file_name=f"{base_name}.md",
    mime="text/markdown",
    width="stretch",
)
export_col2.download_button(
    "Download rapport (.html)",
    data=html_export,
    file_name=f"{base_name}.html",
    mime="text/html",
    width="stretch",
)
export_col3.download_button(
    "Download rapportdata (.json)",
    data=json_export,
    file_name=f"{base_name}.json",
    mime="application/json",
    width="stretch",
)

preview_cards, preview_table = st.tabs(["Kortvisning", "Redigeret tabel"])
with preview_cards:
    if draft_report.servitutter:
        for entry in draft_report.servitutter:
            render_report_entry_card(entry)
    else:
        render_empty_state("Ingen rapportposter", "Rapporten indeholder ingen linjer.")
with preview_table:
    if draft_report.markdown_content:
        st.markdown(draft_report.markdown_content)
    else:
        render_empty_state("Ingen tabel endnu", "Den redigerede rapport har ingen tabel at vise.")
