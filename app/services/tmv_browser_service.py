"""
TMV Playwright-browserservice.

Fuldt automatiseret flow (efter MitID-login):
1. Åbner browser → https://www.tinglysning.dk/tmv/foresporgsel
2. Venter på MitID-login (URL-skift + "Log ud"-knap)
3. Udfylder adresse automatisk fra sagen → klikker Søg
4. Klikker første søgeresultat (navigerer til ejendommens side)
5. Klikker "Servitutter"-dropdown
6. Finder alle a[href*='indskannetakt/rd/']-links og downloader
7. Importerer via import_downloaded_pdfs

Fallback (hvis adresse mangler eller søgning fejler):
→ Status sættes til waiting_for_login med status_detail besked
→ Brugeren navigerer manuelt og klikker "Klar til download" i Streamlit
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

_TMV_URL = "https://www.tinglysning.dk/tmv/foresporgsel"
_LOGIN_TIMEOUT_SECONDS = 300   # 5 min til MitID-login
_USER_READY_TIMEOUT_SECONDS = 600  # 10 min til manuel navigation (fallback)

# Verificerede selektorer (fra DOM-inspektion 2026-03-18)
_SELECTORS = {
    # Login-detektion: URL-fragment + knap der kun er synlig efter login
    "post_login_url":       "/tmv/foresporgsel",
    "login_success_button": "button:has-text('Log ud')",

    # Adressesøgning (første søge-panel)
    "address_input":        "[aria-label='Adresse']",
    "search_button":        "button:has-text('Søg')",

    # Søgeresultater: container der vises efter søgning
    "result_container":     "app-f-result",
    "result_first_link":    "app-f-result a",

    # Ejendomsside — allerede verificeret via Magnus's script
    "servitutter_button":   "button:has-text('Servitutter')",
    "document_link":        "a[href*='indskannetakt/rd/']",
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
    return storage_service.load_tmv_job(case_id, job_id)


def latest_active_job(case_id: str) -> TmvJob | None:
    for job in storage_service.list_tmv_jobs(case_id):
        if job.status in ACTIVE_STATUSES:
            return job
    return None


def cancel_job(case_id: str, job_id: str) -> TmvJob:
    job = storage_service.load_tmv_job(case_id, job_id)
    if job is None:
        raise ValueError(f"Job ikke fundet: {job_id}")
    job.status = "cancelled"
    storage_service.save_tmv_job(job)
    return job


def signal_ready(case_id: str, job_id: str) -> TmvJob:
    """Manuel fallback: sæt user_ready=True når brugeren er navigeret til ejendommen."""
    job = storage_service.load_tmv_job(case_id, job_id)
    if job is None:
        raise ValueError(f"Job ikke fundet: {job_id}")
    job.user_ready = True
    job.status_detail = None
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

        # ------------------------------------------------------------------
        # Trin 1: Vent på MitID-login (automatisk detektion)
        # ------------------------------------------------------------------
        _update(job, "waiting_for_login")
        logger.info(f"TMV job {job.job_id[:8]}: venter på MitID-login (maks {_LOGIN_TIMEOUT_SECONDS}s)")

        deadline = time.time() + _LOGIN_TIMEOUT_SECONDS
        while time.time() < deadline:
            if _is_cancelled(job):
                page.close(); browser.close(); return

            job.last_heartbeat_at = datetime.now(timezone.utc)
            storage_service.save_tmv_job(job)

            try:
                on_foresporgsel = _SELECTORS["post_login_url"] in page.url
                log_ud_visible = page.locator(_SELECTORS["login_success_button"]).count() > 0
                if on_foresporgsel and log_ud_visible:
                    break
            except Exception:
                pass
            time.sleep(2)
        else:
            raise TimeoutError(f"Login-timeout efter {_LOGIN_TIMEOUT_SECONDS}s")

        _update(job, "login_confirmed")

        # ------------------------------------------------------------------
        # Trin 2: Automatisk adressesøgning (eller manuel fallback)
        # ------------------------------------------------------------------
        if job.address:
            try:
                _search_and_select_property(job, page)
            except Exception as exc:
                logger.warning(
                    f"TMV job {job.job_id[:8]}: auto-navigation fejlede ({exc}) "
                    "— falder tilbage til manuel navigation"
                )
                _update(
                    job,
                    "waiting_for_login",
                    status_detail=(
                        f"Adressesøgning fejlede: {exc}. "
                        "Navigér manuelt til ejendommen og klik 'Klar til download'."
                    ),
                )
                _wait_for_user_ready(job, page)
        else:
            _update(
                job,
                "waiting_for_login",
                status_detail="Sagen har ingen adresse. Navigér manuelt til ejendommen og klik 'Klar til download'.",
            )
            _wait_for_user_ready(job, page)

        if _is_cancelled(job):
            page.close(); browser.close(); return

        # ------------------------------------------------------------------
        # Trin 3: Klik Servitutter + download (Magnus's flow)
        # ------------------------------------------------------------------
        _update(job, "listing_documents")
        try:
            page.locator(_SELECTORS["servitutter_button"]).first.click()
            page.wait_for_timeout(2000)
        except Exception as exc:
            raise RuntimeError(
                f"Kunne ikke åbne Servitutter-dropdown: {exc}. "
                "Er siden den rigtige ejendomsside i TMV?"
            ) from exc

        links = page.locator(_SELECTORS["document_link"])
        link_count = links.count()
        logger.info(f"TMV job {job.job_id[:8]}: {link_count} akt-link(s) fundet")

        # Deduplikér på href
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

        logger.info(f"TMV job {job.job_id[:8]}: {len(unique_links)} unikke akt-links")

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
                logger.info(f"TMV job {job.job_id[:8]}: springer over (findes): {filename}")
                continue

            try:
                logger.info(f"TMV job {job.job_id[:8]}: downloader {nr}/{len(unique_links)}: {text}")
                with page.expect_download(timeout=15_000) as dl_info:
                    links.nth(idx).click()
                dl = dl_info.value
                dl.save_as(str(dest))
                downloaded_paths.append(dest)
                job.last_heartbeat_at = datetime.now(timezone.utc)
                job.downloaded_files = [str(p) for p in downloaded_paths]
                storage_service.save_tmv_job(job)
                page.wait_for_timeout(1000)
            except Exception as exc:
                logger.warning(f"TMV job {job.job_id[:8]}: download fejlede for '{text}': {exc}")

        page.close()
        browser.close()

    # ------------------------------------------------------------------
    # Trin 4: Importér via eksisterende service
    # ------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Hjælpefunktioner
# ---------------------------------------------------------------------------

def _search_and_select_property(job: TmvJob, page) -> None:
    """Udfyld adresse, submit søgning, klik første resultat."""
    _update(job, "searching_property")
    logger.info(f"TMV job {job.job_id[:8]}: søger på '{job.address}'")

    # Udfyld adressefeltet
    address_input = page.locator(_SELECTORS["address_input"])
    address_input.wait_for(state="visible", timeout=10_000)
    address_input.clear()
    address_input.fill(job.address)

    # Klik første Søg-knap (den ved Adresse-feltet)
    page.locator(_SELECTORS["search_button"]).first.click()

    # Vent på at app-f-result dukker op
    _update(job, "selecting_property")
    result_container = page.locator(_SELECTORS["result_container"])
    result_container.wait_for(state="visible", timeout=15_000)

    # Klik første resultatlink
    first_link = page.locator(_SELECTORS["result_first_link"]).first
    first_link.wait_for(state="visible", timeout=10_000)
    first_link.click()

    # Vent på at ejendomssiden er klar (Servitutter-knap synlig)
    page.locator(_SELECTORS["servitutter_button"]).first.wait_for(
        state="visible", timeout=15_000
    )
    logger.info(f"TMV job {job.job_id[:8]}: ejendomsside klar")


def _wait_for_user_ready(job: TmvJob, page) -> None:
    """Manuel fallback: poll disk for user_ready=True."""
    logger.info(f"TMV job {job.job_id[:8]}: venter på manuel bruger-signal (maks {_USER_READY_TIMEOUT_SECONDS}s)")
    deadline = time.time() + _USER_READY_TIMEOUT_SECONDS
    while time.time() < deadline:
        if _is_cancelled(job):
            return
        if _is_user_ready(job):
            logger.info(f"TMV job {job.job_id[:8]}: manuel signal modtaget")
            return
        job.last_heartbeat_at = datetime.now(timezone.utc)
        storage_service.save_tmv_job(job)
        time.sleep(2)
    raise TimeoutError(f"Timeout efter {_USER_READY_TIMEOUT_SECONDS}s — ingen bruger-signal.")
