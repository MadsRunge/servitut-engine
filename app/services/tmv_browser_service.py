"""
TMV Playwright-browserservice.

Starter et Playwright-browserjob der:
1. Åbner TMV (https://www.tinglysning.dk/tmv/)
2. Venter på at brugeren logger ind med MitID
3. Søger på adresse (hvis angivet)
4. Downloader PDF-filer via Playwright download-events
5. Importerer via den eksisterende import_downloaded_pdfs-service

Jobstatus skrives løbende til disk — Streamlit poller via get_job().
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.core.logging import get_logger
from app.models.tmv_job import ACTIVE_STATUSES, TmvJob
from app.services import storage_service
from app.services.tinglysning_import_service import import_downloaded_pdfs

logger = get_logger(__name__)

_TMV_URL = "https://www.tinglysning.dk/tmv/"
_LOGIN_TIMEOUT_SECONDS = 300  # 5 min — giver tid til MitID

# Selektorer isoleret her så de kan verificeres og opdateres mod live TMV-DOM
# uden at røre ved flowlogikken.
_SELECTORS = {
    # Tekst/element synligt KUN efter successfuldt login  TODO: verificér mod TMV
    "login_success_indicator": "text=Log ud",
    # URL-fragment der er tilstede PÅ login-siden  TODO: verificér mod TMV
    "login_url_fragment": "/login",
    # URL-fragment der er tilstede EFTER login  TODO: verificér mod TMV
    "post_login_url_fragment": "/tmv/",
    # Søgefelt til adresseindtastning  TODO: verificér mod TMV
    "search_input": "input[placeholder*='adresse']",
    # Submit-knap til søgning  TODO: verificér mod TMV
    "search_button": "button[type='submit']",
    # Links der peger på PDF-dokumenter i dokumentlisten  TODO: verificér mod TMV
    "document_link": "a[href$='.pdf']",
}

_HEARTBEAT_INTERVAL = 10  # sekunder


# ---------------------------------------------------------------------------
# Offentlig API
# ---------------------------------------------------------------------------

def start_job(case_id: str, address: str | None, *, headless: bool = False) -> TmvJob:
    """Opretter et TmvJob, gemmer det på disk og starter Playwright i en thread."""
    if storage_service.load_case(case_id) is None:
        raise ValueError(f"Sag ikke fundet: {case_id}")

    download_dir = str(
        Path(settings.TMV_JOB_DOWNLOAD_DIR).expanduser()
        / case_id
        / str(uuid4())[:8]
    )
    job = TmvJob(
        job_id=str(uuid4()),
        case_id=case_id,
        status="pending",
        started_at=datetime.now(timezone.utc),
        address=address,
        download_dir=download_dir,
    )
    storage_service.save_tmv_job(job)

    thread = threading.Thread(
        target=_run_job,
        args=(job, headless),
        daemon=True,
        name=f"tmv-{job.job_id[:8]}",
    )
    thread.start()
    return job


def get_job(case_id: str, job_id: str) -> TmvJob | None:
    """Læser jobstatus fra disk."""
    return storage_service.load_tmv_job(case_id, job_id)


def latest_active_job(case_id: str) -> TmvJob | None:
    """Returnerer det nyeste aktive (ikke-terminale) job for sagen, eller None."""
    for job in storage_service.list_tmv_jobs(case_id):
        if job.status in ACTIVE_STATUSES:
            return job
    return None


def cancel_job(case_id: str, job_id: str) -> TmvJob:
    """Sætter jobstatus til 'cancelled'. Tråden opdager det ved næste heartbeat-check."""
    job = storage_service.load_tmv_job(case_id, job_id)
    if job is None:
        raise ValueError(f"Job ikke fundet: {job_id}")
    job.status = "cancelled"
    storage_service.save_tmv_job(job)
    return job


# ---------------------------------------------------------------------------
# Intern flow
# ---------------------------------------------------------------------------

def _update(job: TmvJob, status: str, **kwargs) -> TmvJob:
    job.status = status
    job.last_heartbeat_at = datetime.now(timezone.utc)
    for k, v in kwargs.items():
        setattr(job, k, v)
    storage_service.save_tmv_job(job)
    logger.info(f"TMV job {job.job_id[:8]}: {status}")
    return job


def _is_cancelled(job: TmvJob) -> bool:
    """Læser fra disk for at opdage annullering på tværs af tråde."""
    current = storage_service.load_tmv_job(job.case_id, job.job_id)
    return current is not None and current.status == "cancelled"


def _run_job(job: TmvJob, headless: bool) -> None:
    try:
        _execute(job, headless)
    except Exception as exc:
        logger.error(f"TMV job {job.job_id[:8]} fejlede: {exc}", exc_info=True)
        job.status = "failed"
        job.error_message = str(exc)
        job.last_heartbeat_at = datetime.now(timezone.utc)
        storage_service.save_tmv_job(job)


def _execute(job: TmvJob, headless: bool) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright er ikke installeret. "
            "Kør: uv add playwright && uv run playwright install chromium"
        )

    download_dir = Path(job.download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)

    _update(job, "browser_started")

    downloaded_paths: list[Path] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # Registrér download-events — bruges i stedet for filsystem-polling
        pending_downloads: list = []

        def _on_download(dl) -> None:
            pending_downloads.append(dl)

        page.on("download", _on_download)
        page.goto(_TMV_URL)

        # --- Vent på MitID-login ---
        _update(job, "waiting_for_login")

        deadline = time.time() + _LOGIN_TIMEOUT_SECONDS
        while time.time() < deadline:
            if _is_cancelled(job):
                page.close()
                browser.close()
                return

            # Heartbeat hvert 10. sekund
            job.last_heartbeat_at = datetime.now(timezone.utc)
            storage_service.save_tmv_job(job)

            # Login-detektion: URL-skift væk fra login-fragment (primær strategi)
            try:
                current_url = page.url
                not_on_login = _SELECTORS["login_url_fragment"] not in current_url
                on_tmv = _SELECTORS["post_login_url_fragment"] in current_url
                if not_on_login and on_tmv:
                    break
                # Fallback: tjek for login-success-element
                if page.locator(_SELECTORS["login_success_indicator"]).count() > 0:
                    break
            except Exception:
                pass  # Side loader stadig

            time.sleep(2)
        else:
            raise TimeoutError(
                f"Login-timeout efter {_LOGIN_TIMEOUT_SECONDS}s — brugeren loggede ikke ind i tide."
            )

        _update(job, "login_confirmed")

        # --- Adressesøgning ---
        _update(job, "searching_property")
        if job.address:
            try:
                search_input = page.locator(_SELECTORS["search_input"])
                search_input.wait_for(state="visible", timeout=15_000)
                search_input.fill(job.address)
                page.locator(_SELECTORS["search_button"]).click()
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception as exc:
                logger.warning(
                    f"TMV job {job.job_id[:8]}: adressesøgning fejlede ({exc}) — "
                    "brugeren navigerer manuelt"
                )
        else:
            logger.info(f"TMV job {job.job_id[:8]}: ingen adresse — venter 10s på manuel navigation")
            time.sleep(10)

        # --- Find dokumentliste ---
        _update(job, "listing_documents")
        try:
            page.wait_for_selector(_SELECTORS["document_link"], timeout=30_000)
        except Exception as exc:
            logger.warning(f"TMV job {job.job_id[:8]}: ingen PDF-links fundet: {exc}")

        doc_links = page.locator(_SELECTORS["document_link"])
        link_count = doc_links.count()
        logger.info(f"TMV job {job.job_id[:8]}: {link_count} PDF-link(s) fundet")

        # --- Download PDF'er ---
        _update(job, "downloading_documents")
        for i in range(link_count):
            if _is_cancelled(job):
                break
            try:
                with page.expect_download(timeout=30_000) as dl_info:
                    doc_links.nth(i).click()
                dl = dl_info.value
                dest = download_dir / (dl.suggested_filename or f"dok_{i + 1}.pdf")
                dl.save_as(str(dest))
                downloaded_paths.append(dest)
                logger.info(f"TMV job {job.job_id[:8]}: downloaded {dest.name}")
                job.last_heartbeat_at = datetime.now(timezone.utc)
                job.downloaded_files = [str(p) for p in downloaded_paths]
                storage_service.save_tmv_job(job)
            except Exception as exc:
                logger.warning(f"TMV job {job.job_id[:8]}: download {i + 1} fejlede: {exc}")

        page.close()
        browser.close()

    # --- Importér via eksisterende service ---
    _update(job, "importing_documents", downloaded_files=[str(p) for p in downloaded_paths])

    if downloaded_paths:
        result = import_downloaded_pdfs(job.case_id, download_dir)
        summary = (
            f"Importerede {len(result.imported)} · "
            f"Sprang over {len(result.skipped_existing_duplicates) + len(result.skipped_batch_duplicates)} dubletter"
        )
        _update(
            job,
            "completed",
            imported_count=len(result.imported),
            skipped_count=len(result.skipped_existing_duplicates)
            + len(result.skipped_batch_duplicates),
            import_result_summary=summary,
        )
    else:
        _update(job, "completed", import_result_summary="Ingen PDF'er blev downloadet.")
