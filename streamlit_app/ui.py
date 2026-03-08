from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import streamlit as st

from app.models.report import ReportEntry
from app.services import case_service, matrikel_service, storage_service


PIPELINE_STEPS = [
    ("home", "Overblik"),
    ("create", "1. Opret sag"),
    ("upload", "2. Upload"),
    ("ocr", "3. OCR"),
    ("pages", "4. Sider"),
    ("chunks", "5. Chunks"),
    ("extract", "6. Udtræk"),
    ("report", "7. Rapport"),
    ("review", "8. Review"),
]


@dataclass
class CaseStats:
    documents: int
    ocr_ready: int
    pages: int
    chunks: int
    servitutter: int
    reports: int
    case_status: str


def setup_page(title: str, description: str, step: str, layout: str = "wide") -> None:
    st.set_page_config(page_title=title, layout=layout)
    _inject_styles()
    _render_sidebar(step)
    st.markdown(
        f"""
        <section class="hero-shell">
          <div class="hero-eyebrow">Servitut Engine</div>
          <h1>{title}</h1>
          <p>{description}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    render_pipeline_progress(step)


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
          --bg: #f4efe7;
          --card: rgba(255, 252, 247, 0.88);
          --card-strong: #fffaf2;
          --ink: #1f1a17;
          --muted: #6e6259;
          --line: rgba(74, 58, 44, 0.12);
          --accent: #0f766e;
          --accent-soft: rgba(15, 118, 110, 0.12);
          --accent-warm: #c96f2d;
          --success: #2f7d4f;
          --warn: #b7791f;
          --danger: #b84c3d;
        }

        .stApp {
          background:
            radial-gradient(circle at top left, rgba(15, 118, 110, 0.12), transparent 32%),
            radial-gradient(circle at top right, rgba(201, 111, 45, 0.14), transparent 28%),
            linear-gradient(180deg, #f7f2ea 0%, #f1ebe3 100%);
          color: var(--ink);
        }

        [data-testid="stHeader"] {
          background: rgba(244, 239, 231, 0.65);
        }

        [data-testid="stSidebar"] {
          background: linear-gradient(180deg, #1d2a2c 0%, #233536 100%);
        }

        [data-testid="stSidebar"] * {
          color: #f5efe5;
        }

        [data-testid="stSidebar"] .stSelectbox label,
        [data-testid="stSidebar"] .stRadio label,
        [data-testid="stSidebar"] .stTextInput label {
          color: #eadfce !important;
        }

        .hero-shell {
          padding: 1.4rem 1.5rem 1.25rem 1.5rem;
          border: 1px solid var(--line);
          border-radius: 24px;
          background:
            linear-gradient(135deg, rgba(255,255,255,0.9), rgba(255,248,239,0.86)),
            linear-gradient(120deg, rgba(15,118,110,0.08), rgba(201,111,45,0.06));
          box-shadow: 0 20px 50px rgba(53, 42, 33, 0.08);
          margin-bottom: 1rem;
        }

        .hero-shell h1 {
          font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
          font-size: 2.4rem;
          line-height: 1.05;
          margin: 0 0 0.55rem 0;
          letter-spacing: -0.03em;
        }

        .hero-shell p {
          max-width: 62rem;
          color: var(--muted);
          margin: 0;
          font-size: 1rem;
        }

        .hero-eyebrow {
          text-transform: uppercase;
          letter-spacing: 0.16em;
          font-size: 0.72rem;
          color: var(--accent);
          margin-bottom: 0.55rem;
          font-weight: 700;
        }

        .pipeline-row {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
          margin: 0.5rem 0 1.4rem 0;
        }

        .pipeline-pill {
          border-radius: 999px;
          padding: 0.45rem 0.8rem;
          border: 1px solid var(--line);
          background: rgba(255, 250, 242, 0.9);
          color: var(--muted);
          font-size: 0.88rem;
          font-weight: 600;
        }

        .pipeline-pill.active {
          background: linear-gradient(135deg, rgba(15,118,110,0.16), rgba(15,118,110,0.08));
          border-color: rgba(15,118,110,0.22);
          color: var(--accent);
        }

        .section-title {
          font-family: "Iowan Old Style", Georgia, serif;
          font-size: 1.45rem;
          margin: 1.2rem 0 0.6rem 0;
        }

        .section-copy {
          color: var(--muted);
          margin-bottom: 0.8rem;
        }

        .stat-card {
          border: 1px solid var(--line);
          border-radius: 20px;
          padding: 1rem 1rem 0.9rem 1rem;
          background: var(--card);
          box-shadow: 0 16px 32px rgba(48, 37, 29, 0.05);
        }

        .stat-label {
          text-transform: uppercase;
          letter-spacing: 0.12em;
          font-size: 0.7rem;
          color: var(--muted);
          margin-bottom: 0.45rem;
          font-weight: 700;
        }

        .stat-value {
          font-size: 1.8rem;
          line-height: 1;
          color: var(--ink);
          margin-bottom: 0.35rem;
          font-weight: 700;
        }

        .stat-note {
          color: var(--muted);
          font-size: 0.9rem;
        }

        .panel {
          border: 1px solid var(--line);
          border-radius: 22px;
          background: var(--card);
          padding: 1.1rem 1.15rem;
          box-shadow: 0 16px 38px rgba(42, 31, 21, 0.05);
        }

        .mini-note {
          color: var(--muted);
          font-size: 0.92rem;
        }

        .case-chip {
          display: inline-flex;
          padding: 0.35rem 0.65rem;
          border-radius: 999px;
          background: var(--accent-soft);
          color: var(--accent);
          font-size: 0.82rem;
          font-weight: 700;
          margin-right: 0.45rem;
          margin-bottom: 0.45rem;
        }

        .empty-card {
          border: 1px dashed rgba(74, 58, 44, 0.24);
          border-radius: 20px;
          padding: 1.1rem 1rem;
          background: rgba(255, 250, 242, 0.58);
        }

        .report-card {
          border: 1px solid var(--line);
          border-radius: 24px;
          background: linear-gradient(180deg, rgba(255, 252, 247, 0.95), rgba(250, 244, 235, 0.92));
          padding: 1.15rem 1.2rem;
          box-shadow: 0 18px 34px rgba(45, 35, 26, 0.06);
          margin-bottom: 1rem;
        }

        .report-card-head {
          display: flex;
          justify-content: space-between;
          gap: 1rem;
          align-items: flex-start;
          margin-bottom: 0.8rem;
        }

        .report-card-nr {
          width: 2rem;
          height: 2rem;
          border-radius: 999px;
          background: var(--accent-soft);
          color: var(--accent);
          display: inline-flex;
          align-items: center;
          justify-content: center;
          font-weight: 700;
          font-size: 0.95rem;
        }

        .report-card-title {
          font-family: "Iowan Old Style", Georgia, serif;
          font-size: 1.25rem;
          line-height: 1.15;
          margin: 0;
        }

        .report-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 0.75rem 1.2rem;
          margin-top: 0.9rem;
        }

        .report-field-label {
          text-transform: uppercase;
          letter-spacing: 0.12em;
          font-size: 0.68rem;
          color: var(--muted);
          margin-bottom: 0.18rem;
          font-weight: 700;
        }

        .report-field-value {
          color: var(--ink);
          font-size: 0.96rem;
          line-height: 1.55;
        }

        .report-badge {
          display: inline-flex;
          align-items: center;
          gap: 0.35rem;
          padding: 0.32rem 0.62rem;
          border-radius: 999px;
          font-size: 0.78rem;
          font-weight: 700;
          border: 1px solid var(--line);
          background: rgba(255, 250, 242, 0.95);
          color: var(--muted);
        }

        .report-badge.relevant {
          background: rgba(15, 118, 110, 0.12);
          color: var(--accent);
          border-color: rgba(15, 118, 110, 0.18);
        }

        @media (max-width: 900px) {
          .report-grid {
            grid-template-columns: 1fr;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar(active_step: str) -> None:
    with st.sidebar:
        st.markdown("### Servitut Engine")
        st.caption("OCR-first sagsflow for servitutanalyse")
        pills = []
        for step_key, label in PIPELINE_STEPS[1:]:
            state = "active" if step_key == active_step else ""
            pills.append(f'<div class="pipeline-pill {state}">{label}</div>')
        st.markdown("".join(pills), unsafe_allow_html=True)


def render_pipeline_progress(active_step: str) -> None:
    pills = []
    for step_key, label in PIPELINE_STEPS:
        state = "active" if step_key == active_step else ""
        pills.append(f'<div class="pipeline-pill {state}">{label}</div>')
    st.markdown(f'<div class="pipeline-row">{"".join(pills)}</div>', unsafe_allow_html=True)


def render_section(title: str, copy: str | None = None) -> None:
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if copy:
        st.markdown(f'<div class="section-copy">{copy}</div>', unsafe_allow_html=True)


def render_empty_state(title: str, body: str) -> None:
    st.markdown(
        f"""
        <div class="empty-card">
          <strong>{title}</strong><br/>
          <span class="mini-note">{body}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stat_cards(cards: Iterable[tuple[str, str, str]]) -> None:
    cards = list(cards)
    columns = st.columns(len(cards))
    for column, (label, value, note) in zip(columns, cards):
        column.markdown(
            f"""
            <div class="stat-card">
              <div class="stat-label">{label}</div>
              <div class="stat-value">{value}</div>
              <div class="stat-note">{note}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_panel_start(title: str, copy: str | None = None) -> None:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown(f"**{title}**")
    if copy:
        st.caption(copy)


def render_panel_end() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def select_case(label: str = "Aktiv sag", key: str = "active_case_id"):
    cases = case_service.list_cases()
    if not cases:
        render_empty_state("Ingen sager endnu", "Opret først en sag for at arbejde videre i pipeline.")
        st.stop()

    case_labels = {f"{case.name} · {case.case_id}": case.case_id for case in cases}
    current = st.session_state.get(key)
    labels = list(case_labels.keys())
    index = next((i for i, item in enumerate(labels) if case_labels[item] == current), 0)

    selected_label = st.selectbox(label, labels, index=index)
    selected_case_id = case_labels[selected_label]
    st.session_state[key] = selected_case_id
    return next(case for case in cases if case.case_id == selected_case_id)


def select_document(case_id: str, docs, label: str = "Dokument", key: str = "active_doc_id"):
    if not docs:
        render_empty_state("Ingen dokumenter", "Upload PDF-filer for at fortsætte.")
        st.stop()

    doc_labels = {f"{doc.filename} · {doc.document_id}": doc.document_id for doc in docs}
    current = st.session_state.get(key)
    labels = list(doc_labels.keys())
    index = next((i for i, item in enumerate(labels) if doc_labels[item] == current), 0)

    selected_label = st.selectbox(label, labels, index=index)
    selected_doc_id = doc_labels[selected_label]
    st.session_state[key] = selected_doc_id
    return next(doc for doc in docs if doc.document_id == selected_doc_id)


def compute_case_stats(case_id: str) -> CaseStats:
    case = storage_service.load_case(case_id)
    docs = storage_service.list_documents(case_id)
    pages = sum(doc.page_count for doc in docs)
    chunks = sum(doc.chunk_count for doc in docs)
    ocr_ready = sum(1 for doc in docs if doc.parse_status == "ocr_done")
    servitutter = len(storage_service.list_servitutter(case_id))
    reports = len(storage_service.list_reports(case_id))
    return CaseStats(
        documents=len(docs),
        ocr_ready=ocr_ready,
        pages=pages,
        chunks=chunks,
        servitutter=servitutter,
        reports=reports,
        case_status=case.status if case else "ukendt",
    )


def render_case_banner(case) -> None:
    chips = []
    if case.address:
        chips.append(f'<span class="case-chip">{case.address}</span>')
    if case.external_ref:
        chips.append(f'<span class="case-chip">Ref: {case.external_ref}</span>')
    if case.target_matrikel:
        chips.append(f'<span class="case-chip">Målmatrikel: {case.target_matrikel}</span>')
    if case.matrikler:
        chips.append(f'<span class="case-chip">{len(case.matrikler)} matrikler på ejendommen</span>')
    chips.append(f'<span class="case-chip">Status: {case.status}</span>')
    st.markdown("".join(chips), unsafe_allow_html=True)


def select_target_matrikel(case, key: str = "target_matrikel"):
    case = matrikel_service.sync_case_matrikler(case.case_id) or case

    if not case.matrikler:
        st.info("Ingen matrikler fundet endnu. Kør OCR på tinglysningsattesten for at aktivere matrikelvalg.")
        return case

    labels = {
        (
            f"{matrikel.matrikelnummer} · {matrikel.landsejerlav or 'Ukendt landsejerlav'}"
            + (f" · {matrikel.areal_m2} m2" if matrikel.areal_m2 else "")
        ): matrikel.matrikelnummer
        for matrikel in case.matrikler
    }
    current_value = case.target_matrikel or case.matrikler[0].matrikelnummer
    options = list(labels.keys())
    index = next((i for i, label in enumerate(options) if labels[label] == current_value), 0)

    selected_label = st.selectbox(
        "Målmatrikel",
        options,
        index=index,
        key=f"{key}_{case.case_id}",
        help="Redegørelsen og scope-vurderingen køres for den valgte matrikel på ejendommen.",
    )
    selected_value = labels[selected_label]
    if selected_value != case.target_matrikel:
        case = case_service.update_target_matrikel(case.case_id, selected_value) or case
    return case


def render_case_stats(case_id: str) -> CaseStats:
    stats = compute_case_stats(case_id)
    render_stat_cards(
        [
            ("Dokumenter", str(stats.documents), f"{stats.ocr_ready} klar med OCR"),
            ("Sider", str(stats.pages), "OCR-udtrukne sider"),
            ("Chunks", str(stats.chunks), "Klar til udtræk"),
            ("Servitutter", str(stats.servitutter), "Gemte fund"),
            ("Rapporter", str(stats.reports), "Genererede redegørelser"),
        ]
    )
    return stats


def parse_status_label(status: str) -> str:
    return {
        "pending": "Afventer OCR",
        "processing": "Kører OCR",
        "ocr_done": "OCR færdig",
        "error": "Fejl",
    }.get(status, status)


def confidence_band(value: float) -> tuple[str, str]:
    if value >= 0.7:
        return "God", "green"
    if value > 0.0:
        return "Lav", "orange"
    return "Tom", "gray"


def render_report_entry_card(entry: ReportEntry) -> None:
    relevant_class = "relevant" if entry.relevant_for_project else ""
    relevant_label = "Vedrører projekt" if entry.relevant_for_project else "Ikke markeret som projektkritisk"
    st.markdown(
        f"""
        <div class="report-card">
          <div class="report-card-head">
            <div style="display:flex; gap:0.85rem; align-items:flex-start;">
              <div class="report-card-nr">{entry.nr}</div>
              <div>
                <div class="report-card-title">{entry.description or "Ingen beskrivelse"}</div>
                <div class="mini-note">{entry.date_reference or "Dato/løbenummer mangler"}</div>
              </div>
            </div>
            <div class="report-badge {relevant_class}">{relevant_label}</div>
          </div>
          <div class="report-grid">
            <div>
              <div class="report-field-label">Påtaleberettiget</div>
              <div class="report-field-value">{entry.beneficiary or "Ikke angivet"}</div>
            </div>
            <div>
              <div class="report-field-label">Rådighed / Tilstand</div>
              <div class="report-field-value">{entry.disposition or "Ikke angivet"}</div>
            </div>
            <div>
              <div class="report-field-label">Retlig type</div>
              <div class="report-field-value">{entry.legal_type or "Ikke angivet"}</div>
            </div>
            <div>
              <div class="report-field-label">Håndtering / Handling</div>
              <div class="report-field-value">{entry.action or "Ingen handling angivet"}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
