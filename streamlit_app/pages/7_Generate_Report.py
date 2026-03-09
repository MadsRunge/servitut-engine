import sys
from pathlib import Path
import json
import html

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, matrikel_service, storage_service
from app.services.report_service import generate_report
from streamlit_app.ui import (
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_report_entry_card,
    render_section,
    render_stat_cards,
    select_case,
    select_target_matrikel,
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
    f"{m.matrikelnummer} · {m.landsejerlav or 'Ukendt landsejerlav'}"
    + (f" · {m.areal_m2} m²" if m.areal_m2 else ""): m.matrikelnummer
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


def _build_markdown_report(report) -> str:
    parts = [f"# Rapport {report.report_id}", ""]
    if report.target_matrikler:
        parts.extend(
            [
                f"**Projektmatrikler:** {', '.join(report.target_matrikler)}",
                f"**Ejendommens matrikler:** {', '.join(report.available_matrikler) or 'Ikke angivet'}",
                "",
            ]
        )
    if report.notes:
        parts.extend(["## Bemærkninger", report.notes, ""])

    if report.markdown_content:
        parts.extend(["## Tabel", report.markdown_content, ""])
        return "\n".join(parts)

    parts.append("## Rapportposter")
    parts.append("")
    for entry in report.servitutter:
        parts.extend(
            [
                f"### {entry.nr}. {entry.description or 'Ingen beskrivelse'}",
                f"- Dato/løbenummer: {entry.date_reference or 'Ikke angivet'}",
                f"- Påtaleberettiget: {entry.beneficiary or 'Ikke angivet'}",
                f"- Rådighed/tilstand: {entry.disposition or 'Ikke angivet'}",
                f"- Offentlig/privatretlig: {entry.legal_type or 'Ikke angivet'}",
                f"- Håndtering/Handling: {entry.action or 'Ikke angivet'}",
                f"- Vedrører projektområdet: {'Ja' if entry.relevant_for_project else 'Nej'}",
                "",
            ]
        )
    return "\n".join(parts)


def _build_html_report(report, case) -> str:
    case_name = case.name
    address = case.address or "Ikke angivet"
    external_ref = case.external_ref or "Ikke angivet"
    target_matrikel = ", ".join(report.target_matrikler) if report.target_matrikler else "Ikke valgt"
    all_matrikler = ", ".join(report.available_matrikler) or "Ikke angivet"
    relevant_count = sum(1 for entry in report.servitutter if (entry.scope or "") == "Ja")
    maybe_count = sum(1 for entry in report.servitutter if (entry.scope or "Måske") == "Måske")
    non_relevant_count = sum(1 for entry in report.servitutter if (entry.scope or "") == "Nej")

    note_block = ""
    if report.notes:
        note_block = f"""
        <section class="notes">
          <h2>Bemærkninger</h2>
          <p>{html.escape(report.notes)}</p>
        </section>
        """

    rows = []
    for entry in report.servitutter:
        scope = entry.scope or ("Ja" if entry.relevant_for_project else "Måske")
        scope_text = entry.scope_detail or scope
        relevant_class = {"Ja": "relevant-row", "Måske": "maybe-row", "Nej": ""}.get(scope, "")
        relevant_badge_class = {"Ja": "badge badge-relevant", "Måske": "badge badge-maybe", "Nej": "badge"}.get(scope, "badge")
        rows.append(
            f"""
            <tr class="{relevant_class}">
              <td>{entry.nr}</td>
              <td>{html.escape(entry.date_reference or "—")}</td>
              <td>{html.escape(entry.description or "—")}</td>
              <td>{html.escape(entry.beneficiary or "—")}</td>
              <td>{html.escape(entry.disposition or "—")}</td>
              <td>{html.escape(entry.legal_type or "—")}</td>
              <td>{html.escape(entry.action or "—")}</td>
              <td><span class="{relevant_badge_class}">{html.escape(scope_text)}</span></td>
            </tr>
            """
        )

    table_html = f"""
    <section>
      <h2>Rapportposter</h2>
      <table>
        <thead>
          <tr>
            <th>Nr.</th>
            <th>Dato/løbenummer</th>
            <th>Beskrivelse</th>
            <th>Påtaleberettiget</th>
            <th>Rådighed/tilstand</th>
            <th>Offentlig/privatretlig</th>
            <th>Håndtering/Handling</th>
            <th>Vedrører projektområdet</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows) if rows else '<tr><td colspan="8">Ingen rapportposter</td></tr>'}
        </tbody>
      </table>
    </section>
    """

    return f"""
    <!doctype html>
    <html lang="da">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Rapport {html.escape(report.report_id)}</title>
        <style>
          :root {{
            --bg: #f5efe7;
            --paper: #fffdf9;
            --ink: #1e1a17;
            --muted: #665c54;
            --line: #ddd2c6;
            --accent: #0f766e;
            --accent-warm: #c96f2d;
            --accent-soft: rgba(15, 118, 110, 0.12);
            --warm-soft: rgba(201, 111, 45, 0.08);
            --danger-soft: rgba(184, 76, 61, 0.10);
          }}
          body {{
            margin: 0;
            background:
              radial-gradient(circle at top left, rgba(15, 118, 110, 0.10), transparent 28%),
              radial-gradient(circle at top right, rgba(201, 111, 45, 0.12), transparent 24%),
              var(--bg);
            color: var(--ink);
            font: 16px/1.55 Georgia, "Times New Roman", serif;
          }}
          main {{
            max-width: 1200px;
            margin: 40px auto;
            padding: 32px;
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 20px;
            box-shadow: 0 16px 40px rgba(40, 28, 18, 0.08);
          }}
          .page {{
            page-break-after: always;
          }}
          .page:last-child {{
            page-break-after: auto;
          }}
          .cover {{
            min-height: calc(100vh - 144px);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
          }}
          .hero {{
            margin-bottom: 28px;
            padding: 24px 26px;
            border-radius: 18px;
            border: 1px solid var(--line);
            background:
              linear-gradient(135deg, rgba(255,255,255,0.96), rgba(255,247,238,0.92)),
              linear-gradient(120deg, rgba(15,118,110,0.08), rgba(201,111,45,0.06));
          }}
          h1, h2 {{
            margin: 0 0 16px 0;
          }}
          .eyebrow {{
            color: var(--accent);
            text-transform: uppercase;
            letter-spacing: 0.14em;
            font: 700 12px/1.2 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin-bottom: 12px;
          }}
          .meta {{
            color: var(--muted);
            margin-top: 10px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          }}
          .summary-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
            margin: 28px 0;
          }}
          .meta-grid {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
            margin-top: 18px;
          }}
          .meta-card {{
            padding: 12px 14px;
            border-radius: 14px;
            border: 1px solid var(--line);
            background: rgba(255, 252, 247, 0.92);
          }}
          .meta-label {{
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font: 700 11px/1.2 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            color: var(--muted);
            margin-bottom: 6px;
          }}
          .meta-value {{
            font: 600 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            color: var(--ink);
          }}
          .summary-card {{
            padding: 16px 18px;
            border-radius: 16px;
            border: 1px solid var(--line);
            background: rgba(255, 252, 247, 0.95);
          }}
          .summary-number {{
            font: 700 32px/1 "Iowan Old Style", Georgia, serif;
            color: var(--ink);
            margin-bottom: 6px;
          }}
          .summary-copy {{
            font: 600 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            color: var(--muted);
          }}
          .legend {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 14px;
            margin-top: 18px;
          }}
          .legend-card {{
            padding: 16px 18px;
            border-radius: 16px;
            border: 1px solid var(--line);
            background: rgba(255, 251, 245, 0.94);
          }}
          .legend-swatch {{
            display: inline-flex;
            min-width: 78px;
            justify-content: center;
            padding: 6px 12px;
            border-radius: 999px;
            font: 700 12px/1.2 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin-bottom: 10px;
            border: 1px solid var(--line);
          }}
          .legend-swatch.neutral {{
            background: #f4eee6;
            color: var(--muted);
          }}
          .legend-swatch.warn {{
            background: var(--warm-soft);
            color: var(--accent-warm);
          }}
          .legend-swatch.alert {{
            background: var(--danger-soft);
            color: #b84c3d;
          }}
          .notes {{
            margin-bottom: 28px;
            padding: 18px 20px;
            border-radius: 16px;
            background: #f2f7f6;
            border: 1px solid #d6e7e4;
          }}
          table {{
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
          }}
          .report-table-page {{
            background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(251,246,239,0.96));
          }}
          .report-table-header {{
            display: flex;
            justify-content: space-between;
            gap: 18px;
            align-items: flex-start;
            margin-bottom: 18px;
          }}
          .report-table-header h2 {{
            margin-bottom: 8px;
          }}
          .report-table-meta {{
            color: var(--muted);
            font: 500 13px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            text-align: right;
          }}
          .table-wrap {{
            overflow: hidden;
            border-radius: 18px;
            border: 1px solid var(--line);
          }}
          th, td {{
            border: 1px solid var(--line);
            padding: 12px 10px;
            vertical-align: top;
            text-align: left;
            word-break: break-word;
          }}
          th {{
            background: #f8f3ec;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: 13px;
          }}
          tbody tr:nth-child(even) {{
            background: rgba(249, 244, 236, 0.55);
          }}
          tbody tr.relevant-row {{
            background: rgba(15, 118, 110, 0.08);
          }}
          .badge {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 36px;
            padding: 4px 10px;
            border-radius: 999px;
            font: 700 12px/1.2 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            border: 1px solid var(--line);
            background: #f7f1e8;
            color: var(--muted);
          }}
          .badge-relevant {{
            background: var(--accent-soft);
            border-color: rgba(15, 118, 110, 0.18);
            color: var(--accent);
          }}
          .footer-note {{
            margin-top: 24px;
            padding-top: 16px;
            border-top: 1px solid var(--line);
            color: var(--muted);
            font: 500 13px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          }}
          td {{
            font-size: 14px;
          }}
          @media (max-width: 900px) {{
            .summary-grid,
            .legend,
            .meta-grid {{
              grid-template-columns: 1fr;
            }}
            .report-table-header {{
              flex-direction: column;
            }}
            .report-table-meta {{
              text-align: left;
            }}
          }}
          @media print {{
            @page {{
              size: A3 landscape;
              margin: 12mm;
            }}
            body {{
              background: white;
            }}
            main {{
              margin: 0;
              box-shadow: none;
              border: none;
              border-radius: 0;
              max-width: none;
              padding: 0;
            }}
          }}
        </style>
      </head>
      <body>
        <main>
          <section class="page cover">
            <div>
              <section class="hero">
                <div class="eyebrow">Servitut Engine</div>
                <h1>Servitutredegørelse</h1>
                <div class="meta">Struktureret redegørelse med fokus på læsbarhed, sporbarhed og projektrelevans.</div>
                <div class="meta-grid">
                  <div class="meta-card">
                    <div class="meta-label">Sag</div>
                    <div class="meta-value">{html.escape(case_name)}</div>
                  </div>
                  <div class="meta-card">
                    <div class="meta-label">Adresse</div>
                    <div class="meta-value">{html.escape(address)}</div>
                  </div>
                  <div class="meta-card">
                    <div class="meta-label">Journal / Reference</div>
                    <div class="meta-value">{html.escape(external_ref)}</div>
                  </div>
                  <div class="meta-card">
                    <div class="meta-label">Målmatrikel</div>
                    <div class="meta-value">{html.escape(target_matrikel)}</div>
                  </div>
                </div>
              </section>

              <section class="summary-grid">
                <div class="summary-card">
                  <div class="summary-number">{len(report.servitutter)}</div>
                  <div class="summary-copy">Servitutter i rapporten</div>
                </div>
                <div class="summary-card">
                  <div class="summary-number">{relevant_count}</div>
                  <div class="summary-copy">Projektrelevante poster</div>
                </div>
                <div class="summary-card">
                  <div class="summary-number">{non_relevant_count}</div>
                  <div class="summary-copy">Øvrige poster</div>
                </div>
                <div class="summary-card">
                  <div class="summary-number">{report.created_at:%d.%m.%Y}</div>
                  <div class="summary-copy">Rapportdato</div>
                </div>
              </section>

              <section>
                <h2>Afgrænsning</h2>
                <div class="notes">
                  <p>Redegørelsen er afgrænset til målmatriklen <strong>{html.escape(target_matrikel)}</strong>.
                  Ejendommen omfatter matriklerne {html.escape(all_matrikler)}.</p>
                </div>
              </section>

              <section>
                <h2>Vurderingsniveauer</h2>
                <div class="legend">
                  <div class="legend-card">
                    <div class="legend-swatch neutral">Neutral</div>
                    <div>Servitutten vurderes ikke at påvirke projektområdet direkte og kræver normalt ingen yderligere handling.</div>
                  </div>
                  <div class="legend-card">
                    <div class="legend-swatch warn">Afklar</div>
                    <div>Servitutten bør vurderes nærmere i projekteringen eller den juridiske afklaring, før den kan afskrives.</div>
                  </div>
                  <div class="legend-card">
                    <div class="legend-swatch alert">Kritisk</div>
                    <div>Servitutten har tydelig betydning for placering, håndtering eller byggeforudsætninger og skal iagttages aktivt.</div>
                  </div>
                </div>
              </section>
            </div>

            <div class="footer-note">
              Rapport-id: {html.escape(report.report_id)} · Oprettet: {report.created_at} ·
              Projektrelevante poster markeres særskilt i rapporttabellen.
            </div>
          </section>

          <section class="page report-table-page">
            <div class="report-table-header">
              <div>
                <div class="eyebrow">Servitutredegørelse</div>
                <h2>{html.escape(case_name)}</h2>
                <div class="meta">Tabelvisning til browser og print.</div>
              </div>
              <div class="report-table-meta">
                Rapport-id: {html.escape(report.report_id)}<br />
                Oprettet: {report.created_at}<br />
                Journal / Reference: {html.escape(external_ref)}<br />
                Målmatrikel: {html.escape(target_matrikel)}
              </div>
            </div>
            {note_block}
            <div class="table-wrap">
              {table_html}
            </div>
            <div class="footer-note">
              Note: Rapporten er genereret i Servitut Engine og bør kvalitetssikres juridisk, før den anvendes som endelig redegørelse.
            </div>
          </section>
        </main>
      </body>
    </html>
    """


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
        export_col1.download_button(
            "Download rapport (.md)",
            data=markdown_export,
            file_name=f"{report.report_id}.md",
            mime="text/markdown",
            use_container_width=True,
        )
        export_col2.download_button(
            "Download rapport (.html)",
            data=html_export,
            file_name=f"{report.report_id}.html",
            mime="text/html",
            use_container_width=True,
        )
        export_col3.download_button(
            "Download rapportdata (.json)",
            data=json_export,
            file_name=f"{report.report_id}.json",
            mime="application/json",
            use_container_width=True,
        )

        tab_cards, tab_table = st.tabs(["Laesbar visning", "Ra tabel"])
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
