from __future__ import annotations

from typing import Sequence

from app.models.document import PageData


_ATTEST_FILENAME_MARKERS = (
    "tinglysningsattest",
    "ejendomssumaris",
    "ejendomsresume",
    "ejendomsresumé",
)

_ATTEST_TEXT_MARKERS = (
    "tinglysningsattest",
    "tinglyste byrder",
    "landsjerlav:",
    "landsejerlav:",
    "matrikelnummer:",
)

_AKT_TEXT_MARKERS = (
    "deklaration",
    "servitut",
    "påtaleberettiget",
    "anmelder",
)


def validate_document_type(requested_type: str | None) -> str | None:
    if requested_type is None:
        return None
    normalized = requested_type.strip().lower()
    if normalized in {"akt", "tinglysningsattest"}:
        return normalized
    raise ValueError("document_type must be 'akt' or 'tinglysningsattest'")


def classify_document(
    filename: str,
    pages: Sequence[PageData] | None = None,
    requested_type: str | None = None,
) -> str:
    """
    Determine whether a document is a tinglysningsattest or an akt.

    Priority:
    1. Explicit user/API override
    2. OCR/page text from the first pages
    3. Filename heuristics
    4. Default to akt
    """
    normalized_type = validate_document_type(requested_type)
    if normalized_type:
        return normalized_type

    text = "\n".join(page.text for page in (pages or [])[:2]).lower()
    if text:
        if any(marker in text for marker in _ATTEST_TEXT_MARKERS):
            return "tinglysningsattest"
        if sum(1 for marker in _AKT_TEXT_MARKERS if marker in text) >= 2:
            return "akt"

    lowered_filename = filename.lower()
    if any(marker in lowered_filename for marker in _ATTEST_FILENAME_MARKERS):
        return "tinglysningsattest"

    return "akt"
