"""
Tests for tmv_browser_service — kræver IKKE en rigtig browser.
Playwright-importen mockes ud; storage og case-opslag bruger tmp_path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.db.database import create_tables, get_session_ctx, reset_engine_cache
from app.models.case import Case
from app.models.tmv_job import ACTIVE_STATUSES, TERMINAL_STATUSES, TmvJob


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_case(tmp_path, monkeypatch):
    """Opret en minimal testsag i tmp_path-storage."""
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(settings, "TMV_JOB_DOWNLOAD_DIR", str(tmp_path / "tmv-downloads"))
    (tmp_path / "cases").mkdir()
    reset_engine_cache()
    create_tables()

    from app.services.case_service import create_case

    with get_session_ctx() as session:
        case = create_case(session, "Test Sag", address="Testvej 1, 2100 København Ø")
    return case


# ---------------------------------------------------------------------------
# start_job
# ---------------------------------------------------------------------------

def test_start_job_creates_job_on_disk(mock_case, monkeypatch):
    """start_job skal skrive TmvJob til disk og returnere den."""
    from app.services import storage_service, tmv_browser_service

    # Forhindrer at tråden faktisk starter Playwright
    monkeypatch.setattr(
        "app.services.tmv_browser_service._run_job",
        lambda *_: None,
    )
    # Patch threading.Thread.start så tråden ikke reelt kører
    with patch("threading.Thread.start"):
        job = tmv_browser_service.start_job(mock_case.case_id, address="Testvej 1")

    assert job.job_id
    assert job.case_id == mock_case.case_id
    assert job.status == "pending"
    assert job.address == "Testvej 1"

    # Job skal kunne læses fra disk
    with get_session_ctx() as session:
        loaded = storage_service.load_tmv_job(session, mock_case.case_id, job.job_id)
    assert loaded is not None
    assert loaded.job_id == job.job_id
    assert loaded.status == "pending"


def test_start_job_raises_for_unknown_case(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    (tmp_path / "cases").mkdir()
    reset_engine_cache()
    create_tables()

    from app.services import tmv_browser_service

    with pytest.raises(ValueError, match="Sag ikke fundet"):
        tmv_browser_service.start_job("ikke-eksisterende-sag", address=None)


# ---------------------------------------------------------------------------
# get_job
# ---------------------------------------------------------------------------

def test_get_job_returns_none_for_missing(mock_case, monkeypatch):
    from app.services import tmv_browser_service

    result = tmv_browser_service.get_job(mock_case.case_id, "ukendt-job-id")
    assert result is None


def test_get_job_returns_job_for_existing(mock_case, monkeypatch):
    from app.services import storage_service, tmv_browser_service

    job = TmvJob(
        job_id="test-job-1",
        case_id=mock_case.case_id,
        status="waiting_for_login",
        started_at=datetime.now(timezone.utc),
        download_dir="/tmp/test",
    )
    with get_session_ctx() as session:
        storage_service.save_tmv_job(session, job)

    loaded = tmv_browser_service.get_job(mock_case.case_id, "test-job-1")
    assert loaded is not None
    assert loaded.status == "waiting_for_login"


# ---------------------------------------------------------------------------
# cancel_job
# ---------------------------------------------------------------------------

def test_cancel_job_sets_status_cancelled(mock_case, monkeypatch):
    from app.services import storage_service, tmv_browser_service

    job = TmvJob(
        job_id="test-job-cancel",
        case_id=mock_case.case_id,
        status="waiting_for_login",
        started_at=datetime.now(timezone.utc),
        download_dir="/tmp/test",
    )
    with get_session_ctx() as session:
        storage_service.save_tmv_job(session, job)

    cancelled = tmv_browser_service.cancel_job(mock_case.case_id, "test-job-cancel")
    assert cancelled.status == "cancelled"

    # Verificér at status er gemt på disk
    with get_session_ctx() as session:
        on_disk = storage_service.load_tmv_job(session, mock_case.case_id, "test-job-cancel")
    assert on_disk.status == "cancelled"


def test_cancel_job_raises_for_unknown_job(mock_case, monkeypatch):
    from app.services import tmv_browser_service

    with pytest.raises(ValueError, match="Job ikke fundet"):
        tmv_browser_service.cancel_job(mock_case.case_id, "ikke-eksisterende")


# ---------------------------------------------------------------------------
# latest_active_job
# ---------------------------------------------------------------------------

def test_latest_active_job_returns_none_when_no_active(mock_case, monkeypatch):
    from app.services import storage_service, tmv_browser_service

    completed_job = TmvJob(
        job_id="done-job",
        case_id=mock_case.case_id,
        status="completed",
        started_at=datetime.now(timezone.utc),
        download_dir="/tmp/test",
    )
    with get_session_ctx() as session:
        storage_service.save_tmv_job(session, completed_job)

    assert tmv_browser_service.latest_active_job(mock_case.case_id) is None


def test_latest_active_job_returns_active(mock_case, monkeypatch):
    from app.services import storage_service, tmv_browser_service

    active_job = TmvJob(
        job_id="active-job",
        case_id=mock_case.case_id,
        status="waiting_for_login",
        started_at=datetime.now(timezone.utc),
        download_dir="/tmp/test",
    )
    with get_session_ctx() as session:
        storage_service.save_tmv_job(session, active_job)

    found = tmv_browser_service.latest_active_job(mock_case.case_id)
    assert found is not None
    assert found.job_id == "active-job"


# ---------------------------------------------------------------------------
# _update (intern hjælper)
# ---------------------------------------------------------------------------

def test_update_writes_status_and_heartbeat(mock_case, monkeypatch):
    from app.services import storage_service, tmv_browser_service

    job = TmvJob(
        job_id="test-update",
        case_id=mock_case.case_id,
        status="pending",
        started_at=datetime.now(timezone.utc),
        download_dir="/tmp/test",
    )
    with get_session_ctx() as session:
        storage_service.save_tmv_job(session, job)

    tmv_browser_service._update(job, "browser_started")

    with get_session_ctx() as session:
        on_disk = storage_service.load_tmv_job(session, mock_case.case_id, "test-update")
    assert on_disk.status == "browser_started"
    assert on_disk.last_heartbeat_at is not None


# ---------------------------------------------------------------------------
# signal_ready
# ---------------------------------------------------------------------------

def test_signal_ready_sets_user_ready(mock_case, monkeypatch):
    from app.services import storage_service, tmv_browser_service

    job = TmvJob(
        job_id="test-signal",
        case_id=mock_case.case_id,
        status="waiting_for_login",
        started_at=datetime.now(timezone.utc),
        download_dir="/tmp/test",
    )
    with get_session_ctx() as session:
        storage_service.save_tmv_job(session, job)

    updated = tmv_browser_service.signal_ready(mock_case.case_id, "test-signal")
    assert updated.user_ready is True

    with get_session_ctx() as session:
        on_disk = storage_service.load_tmv_job(session, mock_case.case_id, "test-signal")
    assert on_disk.user_ready is True


def test_signal_ready_raises_for_unknown_job(mock_case, monkeypatch):
    from app.services import tmv_browser_service

    with pytest.raises(ValueError, match="Job ikke fundet"):
        tmv_browser_service.signal_ready(mock_case.case_id, "ikke-eksisterende")


# ---------------------------------------------------------------------------
# Status-konstanter
# ---------------------------------------------------------------------------

def test_status_sets_are_disjoint():
    assert ACTIVE_STATUSES.isdisjoint(TERMINAL_STATUSES)
