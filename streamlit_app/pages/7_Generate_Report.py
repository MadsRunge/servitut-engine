import sys
from pathlib import Path
import json
import html

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.services import case_service, storage_service
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

servitutter = storage_service.list_servitutter(case.case_id)
render_section("Rapportgrundlag", f"{len(servitutter)} servitut(ter) er klar til rapportgenerering.")

if st.button("Generer rapport", type="primary"):
    if not servitutter:
        st.error("Ingen servitutter — kør ekstraktion først.")
    else:
        all_chunks = storage_service.load_all_chunks(case.case_id)
        with st.spinner("Genererer rapport..."):
            try:
                report = generate_report(servitutter, all_chunks, case.case_id)
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


def _build_html_report(report, case_name: str) -> str:
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
        relevant = "Ja" if entry.relevant_for_project else "Nej"
        relevant_class = "relevant-row" if entry.relevant_for_project else ""
        relevant_badge_class = "badge badge-relevant" if entry.relevant_for_project else "badge"
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
              <td><span class="{relevant_badge_class}">{relevant}</span></td>
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
            --accent-soft: rgba(15, 118, 110, 0.12);
            --warm-soft: rgba(201, 111, 45, 0.08);
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
          td {{
            font-size: 14px;
          }}
          @media (max-width: 900px) {{
            .meta-grid {{
              grid-template-columns: 1fr;
            }}
          }}
          @media print {{
            body {{
              background: white;
            }}
            main {{
              margin: 0;
              box-shadow: none;
              border: none;
              border-radius: 0;
              max-width: none;
            }}
          }}
        </style>
      </head>
      <body>
        <main>
          <section class="hero">
            <div class="eyebrow">Servitut Engine</div>
            <h1>Servitutrapport</h1>
            <div class="meta">Struktureret redegørelse med fokus på læsbarhed og projektrelevans.</div>
            <div class="meta-grid">
              <div class="meta-card">
                <div class="meta-label">Sag</div>
                <div class="meta-value">{html.escape(case_name)}</div>
              </div>
              <div class="meta-card">
                <div class="meta-label">Rapport-id</div>
                <div class="meta-value">{html.escape(report.report_id)}</div>
              </div>
              <div class="meta-card">
                <div class="meta-label">Oprettet</div>
                <div class="meta-value">{report.created_at}</div>
              </div>
            </div>
          </section>
          <div class="meta">
            Projektrelevante poster er fremhævet med grøn toning i tabellen.
          </div>
          {note_block}
          {table_html}
        </main>
      </body>
    </html>
    """


for report in reports:
    with st.expander(f"Rapport `{report.report_id}` — {report.created_at}"):
        relevant_count = sum(1 for entry in report.servitutter if entry.relevant_for_project)
        render_stat_cards(
            [
                ("Poster", str(len(report.servitutter)), "Samlet antal rapportlinjer"),
                ("Projektrelevante", str(relevant_count), "Markeret som direkte relevante"),
                ("Øvrige", str(max(0, len(report.servitutter) - relevant_count)), "Kræver evt. sekundær vurdering"),
            ]
        )
        if report.notes:
            st.info(report.notes)

        markdown_export = _build_markdown_report(report)
        html_export = _build_html_report(report, case.name)
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
