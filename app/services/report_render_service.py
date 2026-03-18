from __future__ import annotations

import html

from app.models.report import Report, ReportEntry


def escape_markdown_cell(value: object) -> str:
    text = str(value or "—")
    text = " ".join(text.splitlines()).strip()
    return text.replace("|", "\\|")


def build_markdown_table(entries: list[ReportEntry]) -> str:
    header = (
        "| Nr. | Dato/løbenummer | Titel | Byggeri | Beskrivelse | Påtaleberettiget | "
        "Rådighed/tilstand | Offentlig/privatretlig | Håndtering/Handling | Vedrører projektområdet |"
    )
    divider = "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    rows = [
        " | ".join(
            [
                "|",
                escape_markdown_cell(entry.nr),
                escape_markdown_cell(entry.date_reference),
                escape_markdown_cell(entry.title),
                escape_markdown_cell(entry.byggeri_markering),
                escape_markdown_cell(entry.description),
                escape_markdown_cell(entry.beneficiary),
                escape_markdown_cell(entry.disposition),
                escape_markdown_cell(entry.legal_type),
                escape_markdown_cell(entry.action),
                escape_markdown_cell(entry.scope_detail or entry.scope),
                "|",
            ]
        )
        for entry in entries
    ]
    return "\n".join([header, divider, *rows])


def build_markdown_report(report: Report) -> str:
    parts = [f"# Rapport {report.report_id}", ""]
    if report.target_matrikler:
        parts.extend(
            [
                f"**Projektmatrikler:** {', '.join(report.target_matrikler)}",
                f"**Ejendommens matrikler:** {', '.join(report.available_matrikler) or 'Ikke angivet'}",
                f"**Ajour pr. dato:** {report.as_of_date.isoformat() if report.as_of_date else 'Ikke angivet'}",
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


def build_html_report(report: Report, case) -> str:
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
        raw_text_html = f'<span style="font-size:12px;color:#665c54;font-style:italic">{html.escape(entry.raw_text)}</span>' if entry.raw_text else "—"
        amt_badge = (
            ' <span style="color:#c96f2d;font-weight:700;font-size:11px" '
            'title="Amtet er ophørt siden kommunalreformen 2007 — undersøg tilsvarende region">⚠ Amt → Region?</span>'
            if entry.beneficiary_amt_warning else ""
        )
        byggeri_styles = {
            "rød": ("background:#fde8e8;color:#b84c3d;border-color:rgba(184,76,61,0.3)", "rød"),
            "orange": ("background:#fef3e2;color:#c96f2d;border-color:rgba(201,111,45,0.3)", "orange"),
            "sort": ("background:#f4eee6;color:#665c54;border-color:#ddd2c6", "sort"),
        }
        bm = (entry.byggeri_markering or "").lower()
        if bm in byggeri_styles:
            bm_style, bm_label = byggeri_styles[bm]
            byggeri_html = f'<span style="display:inline-flex;padding:3px 9px;border-radius:999px;font:700 11px/1.2 sans-serif;border:1px solid;{bm_style}">{bm_label}</span>'
        else:
            byggeri_html = "—"
        rows.append(
            f"""
            <tr class="{relevant_class}">
              <td>{entry.nr}</td>
              <td>{html.escape(entry.date_reference or "—")}</td>
              <td>{html.escape(entry.title or "—")}</td>
              <td>{byggeri_html}</td>
              <td>{raw_text_html}</td>
              <td>{html.escape(entry.description or "—")}</td>
              <td>{html.escape(entry.beneficiary or "—")}{amt_badge}</td>
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
        <colgroup>
          <col style="width:3%">
          <col style="width:8%">
          <col style="width:8%">
          <col style="width:5%">
          <col style="width:14%">
          <col style="width:15%">
          <col style="width:8%">
          <col style="width:8%">
          <col style="width:8%">
          <col style="width:9%">
          <col style="width:7%">
        </colgroup>
        <thead>
          <tr>
            <th>Nr.</th>
            <th>Dato/løbenummer</th>
            <th>Titel</th>
            <th>Byggeri</th>
            <th>Servituttens tekst</th>
            <th>Servituttens indhold</th>
            <th>Påtaleberettiget</th>
            <th>Rådighed/tilstand</th>
            <th>Offentlig/privatretlig</th>
            <th>Håndtering/Handling</th>
            <th>Vedrører projektområdet</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows) if rows else '<tr><td colspan="11">Ingen rapportposter</td></tr>'}
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
          .legend-swatch.nej {{
            background: #f4eee6;
            color: var(--muted);
          }}
          .legend-swatch.maske {{
            background: var(--warm-soft);
            color: var(--accent-warm);
          }}
          .legend-swatch.ja {{
            background: var(--accent-soft);
            color: var(--accent);
          }}
          .badge-maybe {{
            background: var(--warm-soft);
            border-color: rgba(201, 111, 45, 0.25);
            color: var(--accent-warm);
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
                  <div class="summary-copy">Ja — gælder projektområdet</div>
                </div>
                <div class="summary-card">
                  <div class="summary-number">{maybe_count}</div>
                  <div class="summary-copy">Måske — uafklaret scope</div>
                </div>
                <div class="summary-card">
                  <div class="summary-number">{non_relevant_count}</div>
                  <div class="summary-copy">Nej — gælder ikke</div>
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
                    <div class="legend-swatch nej">Nej</div>
                    <div>Servitutten vurderes ikke at gælde projektområdet og kræver normalt ingen yderligere handling.</div>
                  </div>
                  <div class="legend-card">
                    <div class="legend-swatch maske">Måske</div>
                    <div>Servituttens scope er uafklaret. Bør undersøges nærmere — enten mangler aktindhold eller matrikelreferencen er tvetydig.</div>
                  </div>
                  <div class="legend-card">
                    <div class="legend-swatch ja">Ja</div>
                    <div>Servitutten gælder bekræftet projektområdet og skal iagttages aktivt ved placering og projektering.</div>
                  </div>
                </div>
              </section>
            </div>

            <div class="footer-note">
              Rapport-id: {html.escape(report.report_id)} · Oprettet: {report.created_at.strftime("%Y-%m-%d %H:%M")} ·
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
                Oprettet: {report.created_at.strftime("%Y-%m-%d %H:%M")}<br />
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
