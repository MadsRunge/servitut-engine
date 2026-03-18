import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from app.core.config import settings
from app.services import storage_service, tmv_browser_service
from app.services.case_service import remove_document_from_case
from app.services.document_service import create_document_from_bytes
from app.services.tinglysning_import_service import import_downloaded_pdfs
from app.models.tmv_job import ACTIVE_STATUSES, TERMINAL_STATUSES
from streamlit_app.ui import (
    parse_status_label,
    render_case_banner,
    render_case_stats,
    render_empty_state,
    render_section,
    select_case,
    setup_page,
)

_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "pending":               ("Starter job...", "⏳"),
    "browser_started":       ("Browser åbnet — log ind med MitID og navigér til ejendommen", "🌐"),
    "waiting_for_login":     ("Venter — log ind og navigér til ejendommen i browser-vinduet", "🔐"),
    "listing_documents":     ("Åbner Servitutter og henter akt-links...", "📋"),
    "downloading_documents": ("Downloader PDF'er...", "⬇️"),
    "importing_documents":   ("Importerer til sag...", "📥"),
    "completed":             ("Færdig", "✅"),
    "failed":                ("Fejl opstod", "❌"),
    "cancelled":             ("Annulleret", "🚫"),
}

setup_page(
    "Upload dokumenter",
    "Tilføj PDF-akter til en sag. Upload tinglysningsattesten separat — den bruges som autoritativ kildeliste.",
    step="upload",
)

case = select_case()
render_case_banner(case)
render_case_stats(case.case_id)

download_marker_key = f"tinglysning_download_started_at_{case.case_id}"
playwright_job_key = f"tmv_playwright_job_id_{case.case_id}"


def _save_uploaded_file(uploaded_file, case_id: str, document_type: str) -> str:
    doc = create_document_from_bytes(
        file_bytes=uploaded_file.getvalue(),
        filename=uploaded_file.name,
        case_id=case_id,
        document_type=document_type,
    )
    return doc.document_id


# ---------------------------------------------------------------------------
# Hent fra tinglysning.dk
# ---------------------------------------------------------------------------
render_section(
    "Hent fra tinglysning.dk",
    "Start et automatiseret Playwright-flow eller importér manuelt downloadede PDF'er.",
)

# --- Automatisk TMV-flow (Playwright) ---
st.markdown("#### Automatisk TMV-flow")
st.caption(
    "Playwright åbner en browser, du logger ind med MitID, og resten klares automatisk."
)

# Find eventuelt igangværende job (session state > disk)
active_job_id: str | None = st.session_state.get(playwright_job_key)
active_job = None
if active_job_id:
    active_job = tmv_browser_service.get_job(case.case_id, active_job_id)
if active_job is None:
    # Genfind aktiv job fra disk hvis session state er mistet
    active_job = tmv_browser_service.latest_active_job(case.case_id)
    if active_job:
        st.session_state[playwright_job_key] = active_job.job_id
        active_job_id = active_job.job_id

if active_job and active_job.status in ACTIVE_STATUSES:
    # --- Job kører: vis status og poll ---
    label, icon = _STATUS_LABELS.get(active_job.status, (active_job.status, "⏳"))
    st.info(f"{icon} **{label}**")

    if active_job.last_heartbeat_at:
        age = (datetime.now(timezone.utc) - active_job.last_heartbeat_at).total_seconds()
        if age > 60:
            st.warning(f"Ingen aktivitet de seneste {int(age)}s — browseren er muligvis gået i stå.")

    # "Klar til download"-knap vises kun mens vi venter på brugeren
    if active_job.status == "waiting_for_login" and not active_job.user_ready:
        st.markdown(
            "**1.** Log ind med MitID i browser-vinduet  \n"
            "**2.** Navigér til den rigtige ejendom i TMV  \n"
            "**3.** Klik herunder når du er klar:"
        )
        if st.button("Klar til download", type="primary", use_container_width=True):
            tmv_browser_service.signal_ready(case.case_id, active_job.job_id)
            st.toast("Signal sendt — downloader nu...")
            st.rerun()

    if active_job.downloaded_files:
        st.caption(f"Downloadede filer: {len(active_job.downloaded_files)}")

    if st.button("Annullér job", type="secondary"):
        tmv_browser_service.cancel_job(case.case_id, active_job.job_id)
        st.session_state.pop(playwright_job_key, None)
        st.toast("Job annulleret.")
        st.rerun()

    # Auto-poll hvert 3. sekund mens job kører
    time.sleep(3)
    st.rerun()

elif active_job and active_job.status == "completed":
    st.success(
        f"✅ **Færdig!** {active_job.import_result_summary or ''} "
        f"({len(active_job.downloaded_files)} PDF(er) downloadet)"
    )
    if st.button("Start nyt TMV-flow"):
        st.session_state.pop(playwright_job_key, None)
        st.rerun()

elif active_job and active_job.status == "failed":
    st.error(f"❌ **Job fejlede:** {active_job.error_message or 'Ukendt fejl'}")
    if st.button("Prøv igen"):
        st.session_state.pop(playwright_job_key, None)
        st.rerun()

elif active_job and active_job.status == "cancelled":
    st.info("Job blev annulleret.")
    if st.button("Start nyt TMV-flow"):
        st.session_state.pop(playwright_job_key, None)
        st.rerun()

else:
    # --- Ingen aktivt job: vis start-form ---
    address_default = case.address or ""
    tmv_address = st.text_input(
        "Adresse til TMV-søgning",
        value=address_default,
        help="Adressen indsættes automatisk i TMV's søgefelt efter login.",
    )
    if not address_default:
        st.caption("Tilføj en adresse på opret-siden for at den forvalgt her.")

    if st.button("Start TMV-flow (Playwright)", type="primary", use_container_width=True):
        try:
            job = tmv_browser_service.start_job(
                case.case_id,
                address=tmv_address or None,
                headless=False,
            )
            st.session_state[playwright_job_key] = job.job_id
            st.toast("Browser starter — log ind med MitID i det nye browser-vindue.")
            st.rerun()
        except RuntimeError as exc:
            st.error(str(exc))

# --- Manuel import (fallback) ---
with st.expander("Manuel import (fallback uden Playwright)"):
    st.caption(
        "Download PDF'erne selv fra tinglysning.dk og importér dem herfra. "
        "Kræver ikke Playwright."
    )

    if case.address:
        st.caption(f"Adresse til opslag: **{case.address}**")

    manual_col1, manual_col2 = st.columns([1, 1])
    if manual_col1.button("1. Marker download-start", type="primary", use_container_width=True):
        st.session_state[download_marker_key] = datetime.now(timezone.utc)
        st.toast("Download-markør gemt. Åbn nu TMV og hent PDF'erne.")

    manual_col2.link_button(
        "2. Åbn tinglysning.dk",
        url="https://www.tinglysning.dk/tmv/",
        use_container_width=True,
    )

    marked_at = st.session_state.get(download_marker_key)
    if marked_at:
        st.caption(f"Importer kun PDF'er downloadet efter: `{marked_at.astimezone().strftime('%d-%m-%Y %H:%M:%S')}`")
    else:
        st.caption("Sæt en download-markør før import, så andre PDF'er i mappen ikke kommer med.")

    download_dir = st.text_input(
        "Lokal download-mappe",
        value=str(settings.tinglysning_download_path),
        help="Mappen scannes for PDF-filer nyere end download-markøren.",
        key="manual_download_dir",
    )

    if st.button("3. Importér nye PDF'er", use_container_width=True):
        if not marked_at:
            st.error("Klik først på 'Marker download-start', før du importerer.")
        else:
            try:
                import_result = import_downloaded_pdfs(
                    case.case_id,
                    download_dir,
                    modified_after=marked_at,
                )
            except (FileNotFoundError, NotADirectoryError) as exc:
                st.error(f"Kunne ikke læse download-mappen: {exc}")
            except ValueError as exc:
                st.error(str(exc))
            else:
                if import_result.imported:
                    st.success(
                        f"Importerede {len(import_result.imported)} PDF-fil(er) ud af {import_result.scanned_pdfs} fundne. "
                        f"Spring over: {len(import_result.skipped_existing_duplicates)} eksisterende dubletter, "
                        f"{len(import_result.skipped_batch_duplicates)} batch-dubletter, "
                        f"{len(import_result.skipped_old)} ældre filer."
                    )
                    for doc in import_result.imported:
                        st.caption(f"Tilføjet: **{doc.filename}** (`{doc.document_id}`)")
                else:
                    st.info(
                        f"Ingen nye PDF'er importeret blandt {import_result.scanned_pdfs} fundne. "
                        f"Spring over: {len(import_result.skipped_existing_duplicates)} eksisterende dubletter, "
                        f"{len(import_result.skipped_batch_duplicates)} batch-dubletter, "
                        f"{len(import_result.skipped_old)} ældre filer."
                    )


# --- Tinglysningsattest ---
render_section(
    "Tinglysningsattest",
    "Upload tinglysningsattesten for ejendommen. Den bruges som autoritativ liste over hvilke servitutter der eksisterer.",
)

existing_docs = storage_service.list_documents(case.case_id)
existing_attest = [d for d in existing_docs if d.document_type == "tinglysningsattest"]

if existing_attest:
    st.info(f"Tinglysningsattest allerede uploadet: **{existing_attest[0].filename}** (`{existing_attest[0].document_id}`)")
    with st.expander("🔄 Upload ny version"):
        attest_file = st.file_uploader("Upload tinglysningsattest (PDF)", type=["pdf"], key="attest_upload")
        if attest_file and st.button("Upload ny tinglysningsattest", key="attest_btn"):
            doc_id = _save_uploaded_file(attest_file, case.case_id, "tinglysningsattest")
            st.success(f"Uploadet: **{attest_file.name}** (`{doc_id}`)")
            st.rerun()
else:
    attest_file = st.file_uploader("Upload tinglysningsattest (PDF)", type=["pdf"], key="attest_upload")
    if attest_file and st.button("Upload tinglysningsattest", key="attest_btn", type="primary"):
        doc_id = _save_uploaded_file(attest_file, case.case_id, "tinglysningsattest")
        st.success(f"Uploadet: **{attest_file.name}** (`{doc_id}`)")
        st.rerun()

# --- Akter ---
render_section(
    "Akter",
    "Upload de individuelle akt-PDFer. Disse bruges til at berige servitutterne med fulde detaljer.",
)
st.page_link(
    "pages/2a_Split_PDF.py",
    label="→ Opdel en stor PDF først",
    icon="✂️",
)

akt_files = st.file_uploader(
    "Upload akter (PDF)", type=["pdf"], accept_multiple_files=True, key="akt_upload"
)

if akt_files and st.button("Upload valgte akter", key="akt_btn"):
    for uploaded_file in akt_files:
        doc_id = _save_uploaded_file(uploaded_file, case.case_id, "akt")
        st.success(f"Uploadet: **{uploaded_file.name}** (`{doc_id}`)")
    st.rerun()

# --- Dokumentbibliotek ---
render_section("Dokumentbibliotek", "Oversigt over filer i den aktive sag og deres aktuelle pipeline-status.")
docs = storage_service.list_documents(case.case_id)
if docs:
    for doc in docs:
        is_attest = doc.document_type == "tinglysningsattest"
        type_badge = "📋 Tinglysningsattest" if is_attest else "📄 Akt"
        col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 0.5])
        col1.markdown(f"**{doc.filename}**  \n`{doc.document_id}`")
        col2.caption(type_badge)
        col3.metric("Status", parse_status_label(doc.parse_status))
        col4.metric("Sider", str(doc.page_count))
        if col5.button("🗑", key=f"del_{doc.document_id}", help="Slet dokument"):
            remove_document_from_case(case.case_id, doc.document_id)
            st.toast(f"{doc.filename} slettet")
            st.rerun()
else:
    render_empty_state("Ingen dokumenter endnu", "Upload tinglysningsattest og akter for at fortsætte til OCR.")
