"""Deterministisk block-type klassificering for tinglysningsattest-segmenter.

Trin 1 i attest-pipeline v2:
  OCR-chunks → AttestSegment[] med block_type klassificeret
"""
from __future__ import annotations

import re

from app.models.attest import AttestBlockType

# Genbrug eksisterende dato/løbenummer-mønster fra attest_pipeline.py
_DATE_REFERENCE_PATTERN = re.compile(r"\b\d{2}\.\d{2}\.\d{4}-[0-9A-Za-z./-]+\b")

# Prioritetsblok-start mønstre
_DECLARATION_START_PATTERNS = [
    re.compile(r"^\s*Prioritet\s+\d+", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Dokument\s+\d+", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Dokumenttype\s*:", re.IGNORECASE | re.MULTILINE),
    # Tinglysningsnummer i starten af en blok (fx "14. Deklaration vedr.")
    re.compile(r"^\s*\d{1,3}\.\s+[A-ZÆØÅ]", re.MULTILINE),
]

# Præcise aflysnings-mønstre (fra plan)
_AFLYSNING_PATTERNS = [
    re.compile(r"Aflyst\s+den\s+\d{2}\.\d{2}\.\d{4}", re.IGNORECASE),
    re.compile(r"Aflyst\s+\d{2}\.\d{2}\.\d{4}", re.IGNORECASE),
    re.compile(r"\bAflyses\b", re.IGNORECASE),
    re.compile(r"Tinglyst\s+aflysning", re.IGNORECASE),
    re.compile(r"Aflysning\s+tinglyst", re.IGNORECASE),
    re.compile(r"^\s*Aflyst\s*$", re.IGNORECASE | re.MULTILINE),
]

_ANMERKNING_HEADER = re.compile(r"\bAnm[æe]rkninger?\b", re.IGNORECASE)

# Minimumsantal date_reference-matches i en FANOUT-sektion
_FANOUT_MIN_DATE_REFS = 3


def _has_declaration_start(text: str) -> bool:
    head = "\n".join(text.splitlines()[:12])
    return any(p.search(head) for p in _DECLARATION_START_PATTERNS)


def _has_aflysning(text: str) -> bool:
    return any(p.search(text) for p in _AFLYSNING_PATTERNS)


def _has_anmerkning_header(text: str) -> bool:
    return bool(_ANMERKNING_HEADER.search(text))


def _count_date_references(text: str) -> int:
    return len(_DATE_REFERENCE_PATTERN.findall(text))


def classify_segment_block_type(segment_text: str) -> AttestBlockType:
    """Klassificér et segment deterministisk.

    Prioritetsrækkefølge:
    1. DECLARATION_START  — ny prioritetsblok begynder
    2. AFLYSNING          — eksplicitte aflysnings-mønstre
    3. ANMERKNING_FANOUT  — Anmærkninger-header + ≥3 date_references
    4. ANMERKNING_TEXT    — Anmærkninger-header uden fan-out
    5. DECLARATION_CONTINUATION — fritekst-continuation
    6. UNKNOWN            — kan ikke klassificeres
    """
    if not segment_text or not segment_text.strip():
        return AttestBlockType.UNKNOWN

    if _has_declaration_start(segment_text):
        return AttestBlockType.DECLARATION_START

    if _has_aflysning(segment_text):
        return AttestBlockType.AFLYSNING

    if _has_anmerkning_header(segment_text):
        if _count_date_references(segment_text) >= _FANOUT_MIN_DATE_REFS:
            return AttestBlockType.ANMERKNING_FANOUT
        return AttestBlockType.ANMERKNING_TEXT

    if segment_text.strip():
        return AttestBlockType.DECLARATION_CONTINUATION

    return AttestBlockType.UNKNOWN
