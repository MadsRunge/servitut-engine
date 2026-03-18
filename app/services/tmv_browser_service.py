"""
TMV Playwright-browserservice.

Flow (baseret på Magnus's script):
1. Åbner browser → brugeren logger ind med MitID og navigerer til ejendommen
2. Brugeren klikker "Klar til download" i Streamlit (sætter job.user_ready = True)
3. Servicen klikker på "Servitutter"-dropdown
4. Finder alle a[href*='indskannetakt/rd/']-links
5. Downloader hver fil og navngiver efter link-tekst
6. Importerer via den eksisterende import_downloaded_pdfs-service
"""
from __future__ import annotations

import re
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
_USER_READY_TIMEOUT_SECONDS = 600  # 10 min til login + navigation

_SELECTORS = {
    # Dropdown-knap med alle servitutter  (verificeret via Magnus's script)
    "servitutter_button": "button:has-text('Servitutter')",
    # Direkte links til individuelle akter  (verificeret via Magnus's script)
    "document_link": "a[href*='indskannetakt/rd/']",
}


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
    """Sætter jobstatus til 'cancelled'. Tråden opdager det ved næste disk-check."""
    job = storage_service.load_tmv_job(case_id, job_id)
    if job is None:
        raise ValueError(f"Job ikke fundet: {job_id}")
    job.status = "cancelled"
    storage_service.save_tmv_job(job)
    return job


def signal_ready(case_id: str, job_id: str) -> TmvJob:
    """
    Sæt user_ready = True — kaldes af Streamlit når brugeren er
    logget ind og navigeret til ejendommen i TMV-browseren.
    """
    job = storage_service.load_tmv_job(case_id, job_id)
    if job is None:
        raise ValueError(f"Job ikke fundet: {job_id}")
    job.user_ready = True
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
    current = storage_service.load_tmv_job(job.case_id, job.job_id)
    return current is not None and current.status == "cancelled"


def _is_user_ready(job: TmvJob) -> bool:
    current = storage_service.load_tmv_job(job.case_id, job.job_id)
    return current is not None and current.user_ready


def _clean_name(name: str) -> str:
    """Renser link-tekst til et gyldigt filnavn (samme logik som Magnus's script)."""
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "fil"


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

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.goto(_TMV_URL)

        # --- Vent på at brugeren er klar (login + navigation til ejendom) ---
        _update(job, "waiting_for_login")
        logger.info(
            f"TMV job {job.job_id[:8]}: venter på bruger-signal "
            f"(maks {_USER_READY_TIMEOUT_SECONDS}s)"
        )

        deadline = time.time() + _USER_READY_TIMEOUT_SECONDS
        while time.time() < deadline:
            if _is_cancelled(job):
                page.close()
                browser.close()
                return
            if _is_user_ready(job):
                break
            # Heartbeat
            job.last_heartbeat_at = datetime.now(timezone.utc)
            storage_service.save_tmv_job(job)
            time.sleep(2)
        else:
            raise TimeoutError(
                f"Timeout efter {_USER_READY_TIMEOUT_SECONDS}s — "
                "brugeren nåede ikke at signalere klar."
            )

        logger.info(f"TMV job {job.job_id[:8]}: bruger-signal modtaget")

        # --- Klik på Servitutter-dropdown ---
        _update(job, "listing_documents")
        try:
            servitutter_btn = page.locator(_SELECTORS["servitutter_button"]).first
            servitutter_btn.click()
            page.wait_for_timeout(2000)
        except Exception as exc:
            raise RuntimeError(
                f"Kunne ikke åbne Servitutter-dropdown: {exc}. "
                "Er siden den rigtige TMV-ejendomsside?"
            ) from exc

        # --- Find unikke PDF-links ---
        links = page.locator(_SELECTORS["document_link"])
        link_count = links.count()
        logger.info(f"TMV job {job.job_id[:8]}: {link_count} akt-link(s) fundet")

        # Deduplikér på href (samme som Magnus's script)
        unique_links: dict[str, dict] = {}
        for i in range(link_count):
            try:
                href = links.nth(i).get_attribute("href") or ""
            except Exception:
                continue
            try:
                text = links.nth(i).inner_text(timeout=1000).strip()
            except Exception:
                text = ""
            if href and href not in unique_links:
                unique_links[href] = {"text": text, "index": i}

        logger.info(
            f"TMV job {job.job_id[:8]}: {len(unique_links)} unikke akt-links efter dedup"
        )

        # --- Download ---
        _update(job, "downloading_documents")
        downloaded_paths: list[Path] = []

        for nr, (href, info) in enumerate(unique_links.values(), start=1):
            if _is_cancelled(job):
                break
            text = info["text"] or f"akt_{nr}"
            idx = info["index"]

            filename = _clean_name(text)
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
            dest = download_dir / filename

            if dest.exists():
                logger.info(f"TMV job {job.job_id[:8]}: springer over (findes allerede): {filename}")
                continue

            try:
                logger.info(f"TMV job {job.job_id[:8]}: downloader {nr}/{len(unique_links)}: {text}")
                with page.expect_download(timeout=15_000) as dl_info:
                    links.nth(idx).click()
                dl = dl_info.value
                dl.save_as(str(dest))
                downloaded_paths.append(dest)
                logger.info(f"TMV job {job.job_id[:8]}: gemt {filename}")

                job.last_heartbeat_at = datetime.now(timezone.utc)
                job.downloaded_files = [str(p) for p in downloaded_paths]
                storage_service.save_tmv_job(job)

                page.wait_for_timeout(1000)
            except Exception as exc:
                logger.warning(f"TMV job {job.job_id[:8]}: download fejlede for '{text}': {exc}")

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
