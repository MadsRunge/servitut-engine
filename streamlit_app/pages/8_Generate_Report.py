from queue import Empty, Queue
import sys
import threading
import time
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

_RP_THREAD = "report_thread"
_RP_RESULT = "report_result"
_RP_START  = "report_start"
_RP_QUEUE  = "report_queue"


def _drain_report_messages() -> None:
    message_queue = st.session_state.get(_RP_QUEUE)
    if message_queue is None:
        return

    latest_result = st.session_state.get(_RP_RESULT)

    while True:
        try:
            message = message_queue.get_nowait()
        except Empty:
            break

        if message["type"] == "result":
            latest_result = (message.get("report"), message.get("error"))

    if latest_result is not None:
        st.session_state[_RP_RESULT] = latest_result

if _RP_THREAD in st.session_state:
    thread = st.session_state[_RP_THREAD]
    _drain_report_messages()
    elapsed = int(time.time() - st.session_state[_RP_START])
    st.info(f"Genererer rapport... **{elapsed}s** forløbet")
    if not thread.is_alive():
        _drain_report_messages()
        report, error = st.session_state.pop(_RP_RESULT, (None, "Ukendt fejl"))
        st.session_state.pop(_RP_THREAD)
        st.session_state.pop(_RP_START, None)
        st.session_state.pop(_RP_QUEUE, None)
        if error:
            st.error(f"Fejl: {error}")
        else:
            storage_service.save_report(report)
            st.success(f"Rapport genereret: `{report.report_id}`")
            st.rerun()
    else:
        time.sleep(1)
        st.rerun()
elif st.button("Generer redegørelse", type="primary"):
    all_chunks = storage_service.load_all_chunks(case.case_id)
    result_queue: Queue = Queue()
    st.session_state[_RP_QUEUE] = result_queue

    def _report_thread(
        srvs=servitutter,
        chunks=all_chunks,
        c_id=case.case_id,
        tm=selected_matrikler,
        am=[m.matrikelnummer for m in case.matrikler],
        aod=as_of_date,
        message_queue=result_queue,
    ):
        try:
            r = generate_report(srvs, chunks, c_id,
                                target_matrikler=tm, available_matrikler=am, as_of_date=aod)
            message_queue.put({"type": "result", "report": r, "error": None})
        except Exception as e:
            message_queue.put({"type": "result", "report": None, "error": str(e)})

    t = threading.Thread(target=_report_thread, daemon=True)
    st.session_state[_RP_THREAD] = t
    st.session_state[_RP_START] = time.time()
    t.start()
    st.rerun()

reports = storage_service.list_reports(case.case_id)
reports_sorted = sorted(reports, key=lambda r: r.created_at, reverse=True)

if not reports_sorted:
    render_empty_state("Ingen rapporter endnu", "Generér den første redegørelse, når servitutterne er gennemgået.")
else:
    latest = reports_sorted[0]

    render_section("Seneste redegørelse", f"Rapport `{latest.report_id}` · {latest.created_at:%Y-%m-%d %H:%M}")

    ja = sum(1 for e in latest.servitutter if (e.scope or "") == "Ja")
    mske = sum(1 for e in latest.servitutter if (e.scope or "Måske") == "Måske")
    nej = sum(1 for e in latest.servitutter if (e.scope or "") == "Nej")
    render_stat_cards(
        [
            ("Poster", str(len(latest.servitutter)), "Samlet antal rapportlinjer"),
            ("Ja", str(ja), "Gælder målmatriklen"),
            ("Måske", str(mske), "Uafklaret scope"),
            ("Nej", str(nej), "Gælder ikke målmatriklen"),
        ]
    )
    if latest.target_matrikler:
        st.caption(
            f"Projektmatrikler: {', '.join(latest.target_matrikler)} · "
            f"Ejendommens matrikler: {', '.join(latest.available_matrikler) or '—'}"
        )
    if latest.notes:
        st.info(latest.notes)

    # Export
    matrikel_slug = "-".join(latest.target_matrikler) if latest.target_matrikler else "ukendt"
    date_slug = latest.created_at.strftime("%Y-%m-%d")
    case_slug = case.name.replace(" ", "_").replace("/", "-")[:40]
    base_name = f"servitutredegoerelse_{case_slug}_{matrikel_slug}_{date_slug}"
    markdown_export = build_markdown_report(latest)
    html_export = build_html_report(latest, case)
    json_export = json.dumps(latest.model_dump(mode="json"), ensure_ascii=False, indent=2)

    exp_col1, exp_col2, exp_col3, edit_col = st.columns([2, 2, 2, 3])
    exp_col1.download_button(
        "Download (.md)",
        data=markdown_export,
        file_name=f"{base_name}.md",
        mime="text/markdown",
        width="stretch",
        key=f"download_md_{latest.report_id}",
    )
    exp_col2.download_button(
        "Download (.html)",
        data=html_export,
        file_name=f"{base_name}.html",
        mime="text/html",
        width="stretch",
        key=f"download_html_{latest.report_id}",
    )
    exp_col3.download_button(
        "Download (.json)",
        data=json_export,
        file_name=f"{base_name}.json",
        mime="application/json",
        width="stretch",
        key=f"download_json_{latest.report_id}",
    )
    with edit_col:
        st.page_link("pages/9_Edit_Report.py", label="Redigér denne rapport", icon="✍️")

    # Preview
    tab_cards, tab_table = st.tabs(["Kortvisning", "Redigeret tabel"])
    with tab_cards:
        if latest.servitutter:
            for entry in latest.servitutter:
                render_report_entry_card(entry)
        else:
            render_empty_state("Ingen rapportposter", "Rapporten indeholder ingen strukturerede linjer.")
    with tab_table:
        if latest.markdown_content:
            st.markdown(latest.markdown_content)
        elif latest.servitutter:
            for entry in latest.servitutter:
                st.markdown(
                    f"**{entry.nr}.** {entry.description or '—'} "
                    f"| {entry.legal_type or '—'} | {entry.action or '—'}"
                )
        else:
            render_empty_state("Ingen tabel endnu", "Rapporten har ingen markdown-tabel at vise.")

    # Ældre rapporter
    if len(reports_sorted) > 1:
        render_section("Tidligere rapporter", "")
        for report in reports_sorted[1:]:
            with st.expander(f"Rapport `{report.report_id}` — {report.created_at:%Y-%m-%d %H:%M}"):
                ja_old = sum(1 for e in report.servitutter if (e.scope or "") == "Ja")
                mske_old = sum(1 for e in report.servitutter if (e.scope or "Måske") == "Måske")
                nej_old = sum(1 for e in report.servitutter if (e.scope or "") == "Nej")
                render_stat_cards(
                    [
                        ("Poster", str(len(report.servitutter)), "Samlet antal rapportlinjer"),
                        ("Ja", str(ja_old), "Gælder målmatriklen"),
                        ("Måske", str(mske_old), "Uafklaret scope"),
                        ("Nej", str(nej_old), "Gælder ikke målmatriklen"),
                    ]
                )
                if report.notes:
                    st.info(report.notes)
                matrikel_slug_old = "-".join(report.target_matrikler) if report.target_matrikler else "ukendt"
                date_slug_old = report.created_at.strftime("%Y-%m-%d")
                base_name_old = f"servitutredegoerelse_{case_slug}_{matrikel_slug_old}_{date_slug_old}"
                c1, c2, c3 = st.columns(3)
                c1.download_button(
                    "Download (.md)",
                    data=build_markdown_report(report),
                    file_name=f"{base_name_old}.md",
                    mime="text/markdown",
                    width="stretch",
                    key=f"download_md_{report.report_id}",
                )
                c2.download_button(
                    "Download (.html)",
                    data=build_html_report(report, case),
                    file_name=f"{base_name_old}.html",
                    mime="text/html",
                    width="stretch",
                    key=f"download_html_{report.report_id}",
                )
                c3.download_button(
                    "Download (.json)",
                    data=json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
                    file_name=f"{base_name_old}.json",
                    mime="application/json",
                    width="stretch",
                    key=f"download_json_{report.report_id}",
                )
