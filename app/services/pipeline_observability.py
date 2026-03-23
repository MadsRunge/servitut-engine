from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.utils.files import save_json


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)


def _observability_dir(case_id: str, pipeline: str) -> Path:
    return settings.cases_path / case_id / "observability" / pipeline


def write_ocr_run_summary(
    case_id: str,
    doc_id: str,
    payload: dict[str, Any],
    *,
    run_id: str | None = None,
) -> Path:
    safe_doc_id = _slug(doc_id)
    safe_run_id = _slug(run_id or _timestamp_slug())
    path = _observability_dir(case_id, "ocr") / f"{safe_doc_id}_{safe_run_id}.json"
    save_json(path, payload)
    return path


def write_extraction_run_summary(
    case_id: str,
    payload: dict[str, Any],
    *,
    run_id: str | None = None,
) -> Path:
    safe_run_id = _slug(run_id or _timestamp_slug())
    path = _observability_dir(case_id, "extraction") / f"{safe_run_id}.json"
    save_json(path, payload)
    return path
