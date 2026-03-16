from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.report import Report, ReportEntry
from app.services.report_render_service import build_markdown_table


def report_to_editor_rows(report: Report) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in report.servitutter:
        rows.append(
            {
                "nr": entry.nr,
                "date_reference": entry.date_reference or "",
                "raw_text": entry.raw_text or "",
                "description": entry.description or "",
                "beneficiary": entry.beneficiary or "",
                "disposition": entry.disposition or "",
                "legal_type": entry.legal_type or "",
                "action": entry.action or "",
                "scope": entry.scope or "",
                "scope_detail": entry.scope_detail or "",
                "relevant_for_project": entry.relevant_for_project,
                "servitut_id": entry.servitut_id,
            }
        )
    return rows


def update_report_from_editor(report: Report, rows: Any, notes: str | None = None) -> Report:
    row_dicts = _coerce_rows(rows)
    indexed_rows = list(enumerate(row_dicts))
    sorted_rows = [
        row
        for _, row in sorted(
            indexed_rows,
            key=lambda item: (_coerce_int(item[1].get("nr"), fallback=10_000), item[0]),
        )
    ]

    entries: list[ReportEntry] = []
    for index, row in enumerate(sorted_rows, start=1):
        entries.append(
            ReportEntry(
                nr=index,
                date_reference=_optional_str(row.get("date_reference")),
                raw_text=_optional_str(row.get("raw_text")),
                description=_optional_str(row.get("description")),
                beneficiary=_optional_str(row.get("beneficiary")),
                disposition=_optional_str(row.get("disposition")),
                legal_type=_optional_str(row.get("legal_type")),
                action=_optional_str(row.get("action")),
                relevant_for_project=bool(row.get("relevant_for_project")),
                scope=_optional_str(row.get("scope")),
                scope_detail=_optional_str(row.get("scope_detail")),
                servitut_id=_required_servitut_id(row.get("servitut_id"), index),
            )
        )

    report.servitutter = entries
    report.notes = _optional_str(notes)
    report.markdown_content = build_markdown_table(entries) if entries else None
    report.edited_at = datetime.utcnow()
    report.manually_edited = True
    return report


def _coerce_rows(rows: Any) -> list[dict[str, Any]]:
    if hasattr(rows, "to_dict"):
        try:
            rows = rows.to_dict("records")
        except TypeError:
            rows = rows.to_dict()
    if isinstance(rows, list):
        return [dict(row) for row in rows if isinstance(row, dict)]
    if isinstance(rows, tuple):
        return [dict(row) for row in rows if isinstance(row, dict)]
    raise ValueError("Redigerede rapportrækker kunne ikke læses")


def _coerce_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _required_servitut_id(value: Any, index: int) -> str:
    text = _optional_str(value)
    if text:
        return text
    return f"manual-row-{index}"
