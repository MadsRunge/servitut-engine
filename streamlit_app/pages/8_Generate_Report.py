import sys
from datetime import date
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import matrikel_service, storage_service
from app.services.report_render_service import build_html_report, build_markdown_report
from app.services.report_service import generate_report
from streamlit_app.ui import (
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_report_entry_card,
    render_section,
    render_stat_cards,
    select_case,
    setup_page,
)

setup_page(
    "Generer redegørelse",
    "Saml de udtrukne servitutter i en læsbar rapport med sporbarhed til chunks og OCR-tekst.",
    step="report",
)

case = select_case()
render_case_banner(case)
render_case_stats(case.case_id)

# --- Matrikelvalg ---
render_section(
    "Vælg projektmatrikler",
    "Vælg én eller flere matrikler som udgør projektområdet. Redegørelsen vurderer alle servitutter mod de valgte matrikler.",
)

if not case.matrikler:
    st.warning("Ingen matrikler fundet på sagen. Kør OCR på tinglysningsattesten for at aktivere matrikelvalg.", icon="⚠️")
    st.stop()

matrikel_labels = {
    f"{m.matrikelnummer} · {m.landsejerlav or 'Ukendt landsejerlav'}": m.matrikelnummer
    for m in case.matrikler
}
all_options = list(matrikel_labels.keys())

# Default: pre-select current target_matrikel if set, otherwise first
default_labels = (
    [lbl for lbl, nr in matrikel_labels.items() if nr == case.target_matrikel]
    if case.target_matrikel
    else [all_options[0]]
)

selected_labels = st.multiselect(
    "Projektmatrikler for denne redegørelse",
    options=all_options,
    default=default_labels,
    help="Vælg alle matrikler der indgår i projektområdet. Servitutter vurderes samlet mod disse.",
)
selected_matrikler = [matrikel_labels[lbl] for lbl in selected_labels]

if not selected_matrikler:
    st.warning("Vælg mindst én matrikel for at fortsætte.", icon="⚠️")
    st.stop()

st.divider()

historical_mode = st.toggle(
    "Afgræns redegørelsen til en historisk dato",
    value=False,
    help="Brug dette når rapporten skal afspejle servitutbilledet pr. en bestemt dato.",
)
as_of_date = None
if historical_mode:
    as_of_date = st.date_input(
        "Servitutredegørelse pr. dato",
        value=date.today(),
        help="Servitutter med tinglysningsdato efter denne dato udelades fra rapporten.",
    )
    st.caption(f"Historisk afgrænsning aktiv: {as_of_date.isoformat()}")

st.divider()

servitutter = matrikel_service.filter_servitutter_for_target(
    storage_service.list_servitutter(case.case_id),
    selected_matrikler,
    available_matrikler=[m.matrikelnummer for m in case.matrikler],
)

ja = sum(1 for s in servitutter if s.applies_to_target_matrikel is True)
mske = sum(1 for s in servitutter if s.applies_to_target_matrikel is None)
nej = sum(1 for s in servitutter if s.applies_to_target_matrikel is False)

st.info(
    f"**{len(servitutter)} servitutter** for **{', '.join(selected_matrikler)}** — "
    f"**{ja} Ja** · **{mske} Måske** · **{nej} Nej**",
    icon="📋",
)

if not servitutter:
    st.warning("Ingen servitutter — kør ekstraktion først.")
    st.stop()

if st.button("Generer redegørelse", type="primary"):
    if not servitutter:
        st.error("Ingen servitutter — kør ekstraktion først.")
    else:
        all_chunks = storage_service.load_all_chunks(case.case_id)
        with st.spinner("Genererer rapport..."):
            try:
                report = generate_report(
                    servitutter,
                    all_chunks,
                    case.case_id,
                    target_matrikler=selected_matrikler,
                    available_matrikler=[m.matrikelnummer for m in case.matrikler],
                    as_of_date=as_of_date,
                )
                storage_service.save_report(report)
                st.success(f"Rapport genereret: `{report.report_id}`")
                st.rerun()
            except Exception as e:
                st.error(f"Fejl: {e}")

render_section("Gemte rapporter", "Tidligere redegørelser for den aktive sag.")
reports = storage_service.list_reports(case.case_id)
if not reports:
    render_empty_state("Ingen rapporter endnu", "Generér den første redegørelse, når servitutterne er gennemgået.")
else:
    st.page_link("pages/9_Edit_Report.py", label="→ Åbn redigeringsvindue", icon="✍️")


for report in reports:
    with st.expander(f"Rapport `{report.report_id}` — {report.created_at}"):
        ja = sum(1 for e in report.servitutter if (e.scope or "") == "Ja")
        mske = sum(1 for e in report.servitutter if (e.scope or "Måske") == "Måske")
        nej = sum(1 for e in report.servitutter if (e.scope or "") == "Nej")
        render_stat_cards(
            [
                ("Poster", str(len(report.servitutter)), "Samlet antal rapportlinjer"),
                ("Ja", str(ja), "Gælder målmatriklen"),
                ("Måske", str(mske), "Uafklaret scope"),
                ("Nej", str(nej), "Gælder ikke målmatriklen"),
            ]
        )
        if report.target_matrikler:
            st.caption(
                f"Projektmatrikler: {', '.join(report.target_matrikler)} · "
                f"Ejendommens matrikler: {', '.join(report.available_matrikler) or '—'}"
            )
        if report.notes:
            st.info(report.notes)

        markdown_export = _build_markdown_report(report)
        html_export = _build_html_report(report, case)
        json_export = json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        export_col1, export_col2, export_col3 = st.columns(3)
        matrikel_slug = "-".join(report.target_matrikler) if report.target_matrikler else "ukendt"
        date_slug = report.created_at.strftime("%Y-%m-%d")
        case_slug = case.name.replace(" ", "_").replace("/", "-")[:40]
        base_name = f"servitutredegoerelse_{case_slug}_{matrikel_slug}_{date_slug}"

        export_col1.download_button(
            "Download rapport (.md)",
            data=markdown_export,
            file_name=f"{base_name}.md",
            mime="text/markdown",
            width="stretch",
            key=f"download_md_{report.report_id}",
        )
        export_col2.download_button(
            "Download rapport (.html)",
            data=html_export,
            file_name=f"{base_name}.html",
            mime="text/html",
            width="stretch",
            key=f"download_html_{report.report_id}",
        )
        export_col3.download_button(
            "Download rapportdata (.json)",
            data=json_export,
            file_name=f"{base_name}.json",
            mime="application/json",
            width="stretch",
            key=f"download_json_{report.report_id}",
        )
        st.page_link("pages/9_Edit_Report.py", label="Redigér denne rapport før endelig eksport", icon="✍️")

        tab_cards, tab_table = st.tabs(["Læsbar visning", "Rapporttabel"])
        with tab_cards:
            if report.servitutter:
                for entry in report.servitutter:
                    render_report_entry_card(entry)
            else:
                render_empty_state("Ingen rapportposter", "Rapporten indeholder ingen strukturerede linjer.")
        with tab_table:
            if report.markdown_content:
                st.markdown(report.markdown_content)
            elif report.servitutter:
                for entry in report.servitutter:
                    st.markdown(
                        f"**{entry.nr}.** {entry.description or '—'} "
                        f"| {entry.legal_type or '—'} | {entry.action or '—'}"
                    )
            else:
                render_empty_state("Ingen tabel endnu", "Rapporten har ingen markdown-tabel at vise.")
