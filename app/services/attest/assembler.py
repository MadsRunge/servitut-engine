"""Assembly af klassificerede AttestSegment-objekter til DeclarationBlock-objekter.

Trin 2 i attest-pipeline v2:
  AttestSegment[] (med block_type) → DeclarationBlock[]
"""
from __future__ import annotations

import hashlib
import re
from typing import Callable, List, Optional

from app.core.logging import get_logger
from app.models.attest import AttestBlockType, AttestSegment, DeclarationBlock

logger = get_logger(__name__)

_DATE_REFERENCE_PATTERN = re.compile(r"\b\d{2}\.\d{2}\.\d{4}-[0-9A-Za-z./-]+\b")
_ARCHIVE_NUMBER_PATTERN = re.compile(
    r"\b(?:\d+\s*[A-ZÆØÅ]\s*-?\s*\d+|[A-ZÆØÅ]-\d+|\d+\s*[A-ZÆØÅ]\s*\d+)\b"
)
_PRIORITY_PATTERN = re.compile(
    r"^\s*(?:Prioritet|Dokument)\s+(\d+)", re.IGNORECASE | re.MULTILINE
)
_TITLE_SKIP = {"tinglysningsattest", "servitutter", "anmærkninger", "anmerkninger"}


def _block_id(segment_ids: List[str]) -> str:
    payload = ":".join(sorted(segment_ids))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _extract_title(text: str) -> Optional[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) < 4:
            continue
        if stripped.lower() in _TITLE_SKIP:
            continue
        # Spring numeriske prioritetslinjer over
        if re.match(r"^\d+\s*[\.\-:]?\s*$", stripped):
            continue
        return stripped[:160]
    return None


def _extract_priority_number(text: str) -> Optional[str]:
    m = _PRIORITY_PATTERN.search(text)
    return m.group(1) if m else None


def _extract_archive_number(text: str) -> Optional[str]:
    matches = _ARCHIVE_NUMBER_PATTERN.findall(text)
    return matches[0] if matches else None


def _extract_scope_line(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if "vedr" in stripped.lower() or "matr" in stripped.lower():
            lines.append(stripped[:240])
    return " ".join(lines)


def _extract_parcel_refs(text: str) -> List[str]:
    scope_text = _extract_scope_line(text)
    parcel_pattern = re.compile(r"\b\d+[a-zæøå]{0,3}\b", re.IGNORECASE)
    seen: dict[str, None] = {}
    for m in parcel_pattern.finditer(scope_text):
        val = m.group(0).lower()
        seen[val] = None
    return list(seen.keys())


def _extract_fanout_date_refs(text: str) -> List[str]:
    seen: dict[str, None] = {}
    for m in _DATE_REFERENCE_PATTERN.finditer(text):
        seen[m.group(0)] = None
    return list(seen.keys())


def _new_block(
    case_id: str,
    doc_id: str,
    segment: AttestSegment,
    orphan: bool = False,
) -> DeclarationBlock:
    title = _extract_title(segment.text) if not orphan else None
    priority_number = _extract_priority_number(segment.text)
    archive_number = _extract_archive_number(segment.text)
    raw_scope_text = _extract_scope_line(segment.text)
    raw_parcel_references = _extract_parcel_refs(segment.text)
    # Saml ALLE date_references fra segmentet, uanset bloktype.
    # Simple blokke (København/Middelfart) har date_ref i DECLARATION_START-teksten.
    # Fan-out blokke (Aalborg) har dem i ANMERKNING_FANOUT-sektioner.
    fanout_refs = _extract_fanout_date_refs(segment.text)

    return DeclarationBlock(
        block_id=_block_id([segment.segment_id]),
        case_id=case_id,
        document_id=doc_id,
        page_start=segment.page_start,
        page_end=segment.page_end,
        source_segment_ids=[segment.segment_id],
        priority_number=priority_number,
        title=title,
        archive_number=archive_number,
        raw_scope_text=raw_scope_text,
        raw_parcel_references=raw_parcel_references,
        has_aflysning=False,
        status="ukendt",
        fanout_date_refs=fanout_refs,
    )


def _merge_segment_into_block(block: DeclarationBlock, segment: AttestSegment) -> None:
    block.source_segment_ids.append(segment.segment_id)
    block.block_id = _block_id(block.source_segment_ids)
    block.page_end = max(block.page_end, segment.page_end)

    # Berig scope hvis segmentet har bedre info
    extra_scope = _extract_scope_line(segment.text)
    if extra_scope and not block.raw_scope_text:
        block.raw_scope_text = extra_scope

    extra_refs = _extract_parcel_refs(segment.text)
    for ref in extra_refs:
        if ref not in block.raw_parcel_references:
            block.raw_parcel_references.append(ref)

    # Berig titel hvis blokken mangler
    if not block.title:
        block.title = _extract_title(segment.text)

    # Berig arkivnummer
    if not block.archive_number:
        block.archive_number = _extract_archive_number(segment.text)

    # AFLYSNING
    if segment.block_type == AttestBlockType.AFLYSNING:
        block.has_aflysning = True
        block.status = "aflyst"

    # Saml ALLE date_references fra segmentet, uanset bloktype.
    new_refs = _extract_fanout_date_refs(segment.text)
    for ref in new_refs:
        if ref not in block.fanout_date_refs:
            block.fanout_date_refs.append(ref)


# Callable type for LLM-fallback (kan overrides i tests)
LLMClassifyFn = Callable[[str], AttestBlockType]


def _default_llm_classify(text: str) -> AttestBlockType:
    """Standard LLM-fallback: kald LLM med smal klassifikations-prompt.

    Importeres lazily for at undgå cirkulære imports.
    """
    try:
        from app.services.attest._llm_classify import llm_classify_block_type
        return llm_classify_block_type(text)
    except Exception:
        logger.warning("LLM-klassifikation af UNKNOWN-blok fejlede — bruger UNKNOWN")
        return AttestBlockType.UNKNOWN


def assemble_declaration_blocks(
    segments: List[AttestSegment],
    case_id: str,
    doc_id: str,
    *,
    llm_classify: Optional[LLMClassifyFn] = None,
) -> List[DeclarationBlock]:
    """Saml klassificerede AttestSegment-objekter til DeclarationBlock-objekter.

    State-machine: akkumulér segmenter ind i den aktuelle blok indtil et nyt
    DECLARATION_START dukker op.

    UNKNOWN-segmenter sendes til LLM-klassifikation og genbehandles.
    """
    if not segments:
        return []

    classify_fn = llm_classify or _default_llm_classify
    ordered = sorted(segments, key=lambda s: s.segment_index)
    blocks: List[DeclarationBlock] = []
    current: Optional[DeclarationBlock] = None

    def emit() -> None:
        if current is not None:
            # Sæt status til aktiv hvis ikke aflyst
            if current.status == "ukendt" and not current.has_aflysning:
                current.status = "aktiv"
            blocks.append(current)

    for segment in ordered:
        block_type = AttestBlockType(segment.block_type)

        # Reklassificér UNKNOWN via LLM
        if block_type == AttestBlockType.UNKNOWN:
            reclassified = classify_fn(segment.text)
            if reclassified != AttestBlockType.UNKNOWN:
                segment.block_type = reclassified
                block_type = reclassified
                logger.debug(
                    "Segment %s reklassificeret via LLM til %s",
                    segment.segment_id,
                    reclassified,
                )

        if block_type == AttestBlockType.DECLARATION_START:
            emit()
            current = _new_block(case_id, doc_id, segment)

        elif block_type in (
            AttestBlockType.DECLARATION_CONTINUATION,
            AttestBlockType.ANMERKNING_FANOUT,
            AttestBlockType.ANMERKNING_TEXT,
            AttestBlockType.AFLYSNING,
        ):
            if current is None:
                logger.debug(
                    "Orphan-segment %s (%s) — opretter orphan-blok",
                    segment.segment_id,
                    block_type,
                )
                current = _new_block(case_id, doc_id, segment, orphan=True)
            else:
                _merge_segment_into_block(current, segment)

        else:
            # UNKNOWN som LLM ikke kunne reklassificere
            if current is None:
                current = _new_block(case_id, doc_id, segment, orphan=True)
                logger.warning(
                    "Uklassificerbart segment %s placeret som orphan-blok",
                    segment.segment_id,
                )
            else:
                _merge_segment_into_block(current, segment)
                logger.warning(
                    "Uklassificerbart segment %s merget ind i aktuel blok",
                    segment.segment_id,
                )

    emit()
    return blocks
