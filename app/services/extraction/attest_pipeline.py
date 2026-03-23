from __future__ import annotations

from datetime import datetime
import hashlib
import re
from typing import Iterable, List, Optional

from sqlmodel import Session

from app.core.logging import get_logger
from app.models.attest import AttestPipelineState, AttestSegment
from app.models.chunk import Chunk
from app.models.servitut import Evidence, Servitut
from app.services import storage_service
from app.services.extraction.llm_extractor import (
    _build_chunks_text,
    _build_servitutter_from_items,
    _max_tokens_for_source_type,
    _parse_llm_response,
    _resolve_extraction_model,
    _resolve_extraction_provider,
)
from app.services.extraction.progress import ProgressCallback, _emit_progress
from app.services.extraction.prompts import _load_prompt
from app.services.llm_service import generate_text

logger = get_logger(__name__)

ATTEST_PIPELINE_VERSION = 1
ATTEST_MAX_SEGMENT_CHARS = 9000
ATTEST_MAX_SEGMENT_PAGES = 4
ATTEST_SEGMENT_OVERLAP_PAGES = 1

_DATE_REFERENCE_PATTERN = re.compile(r"\b\d{2}\.\d{2}\.\d{4}-[0-9A-Za-z./-]+\b")
_ARCHIVE_NUMBER_PATTERN = re.compile(
    r"\b(?:\d+\s*[A-ZÆØÅ]\s*-?\s*\d+|[A-ZÆØÅ]-\d+|\d+\s*[A-ZÆØÅ]\s*\d+)\b"
)
_PARCEL_REFERENCE_PATTERN = re.compile(r"\b\d+[a-zæøå]{0,3}\b", re.IGNORECASE)


class AttestPipelineIncompleteError(RuntimeError):
    def __init__(self, case_id: str, incomplete_docs: list[dict]):
        self.case_id = case_id
        self.incomplete_docs = incomplete_docs
        details = ", ".join(
            f"{item['document_id']} ({item['failed_segments']}/{item['total_segments']} fejlede)"
            for item in incomplete_docs
        )
        super().__init__(
            "Attest extraction incomplete; canonical list was not finalized. "
            f"Case={case_id}; docs={details}"
        )


def _unique_preserve_order(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _normalize_key(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = re.sub(r"[^0-9a-z]+", "", value.lower())
    return normalized or None


def _heading_from_text(text: str) -> Optional[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) < 4:
            continue
        if stripped.lower() in {"tinglysningsattest", "servitutter"}:
            continue
        return stripped[:160]
    return None


def _scope_line_from_text(text: str) -> Optional[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if "vedr" in stripped.lower() or "matr" in stripped.lower():
            return stripped[:240]
    return None


def _parcel_refs_from_text(text: str) -> list[str]:
    scope_text = " ".join(
        line.strip()
        for line in text.splitlines()
        if "vedr" in line.lower() or "matr" in line.lower()
    )
    return _unique_preserve_order(
        match.group(0).lower() for match in _PARCEL_REFERENCE_PATTERN.finditer(scope_text)
    )


def _page_starts_new_entry(page_text: str) -> bool:
    head = "\n".join(page_text.splitlines()[:12])
    return bool(_DATE_REFERENCE_PATTERN.search(head))


def _segment_text_for_pages(page_blocks: list[dict]) -> str:
    parts = []
    for block in page_blocks:
        parts.append(f"[Side {block['page']}]\n{block['text']}")
    return "\n\n".join(parts)


def _source_signature(chunk_list: List[Chunk]) -> str:
    payload = "\n".join(
        f"{chunk.page}:{chunk.chunk_index}:{chunk.text}" for chunk in sorted(
            chunk_list, key=lambda item: (item.page, item.chunk_index)
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _group_chunks_by_page(chunk_list: List[Chunk]) -> list[dict]:
    ordered = sorted(chunk_list, key=lambda item: (item.page, item.chunk_index))
    grouped: list[dict] = []
    current_page: Optional[int] = None
    current_chunks: list[Chunk] = []

    def flush() -> None:
        if not current_chunks:
            return
        grouped.append(
            {
                "page": current_page,
                "chunks": list(current_chunks),
                "text": "\n".join(
                    chunk.text.strip() for chunk in current_chunks if chunk.text.strip()
                ),
            }
        )

    for chunk in ordered:
        if current_page is None or chunk.page != current_page:
            flush()
            current_page = chunk.page
            current_chunks = [chunk]
            continue
        current_chunks.append(chunk)
    flush()
    return grouped


def build_attest_segments(
    case_id: str,
    doc_id: str,
    chunk_list: List[Chunk],
    *,
    max_segment_chars: int = ATTEST_MAX_SEGMENT_CHARS,
    max_segment_pages: int = ATTEST_MAX_SEGMENT_PAGES,
    overlap_pages: int = ATTEST_SEGMENT_OVERLAP_PAGES,
) -> list[AttestSegment]:
    page_blocks = _group_chunks_by_page(chunk_list)
    if not page_blocks:
        return []

    segments: list[AttestSegment] = []
    start = 0
    segment_index = 0

    while start < len(page_blocks):
        end = start
        total_chars = 0
        preferred_end: Optional[int] = None

        while end < len(page_blocks):
            block = page_blocks[end]
            block_chars = len(block["text"])
            reached_page_limit = (end - start) >= max_segment_pages
            reached_char_limit = end > start and total_chars + block_chars > max_segment_chars
            if reached_page_limit or reached_char_limit:
                break
            total_chars += block_chars
            end += 1
            if end < len(page_blocks) and _page_starts_new_entry(page_blocks[end]["text"]):
                preferred_end = end

        if end <= start:
            end = min(start + 1, len(page_blocks))
        elif preferred_end and preferred_end > start:
            end = preferred_end

        selected_blocks = page_blocks[start:end]
        segment_chunks = [chunk for block in selected_blocks for chunk in block["chunks"]]
        segment_text = _segment_text_for_pages(selected_blocks)
        heading = _heading_from_text(segment_text)
        raw_scope_text = _scope_line_from_text(segment_text)
        segment = AttestSegment(
            segment_id=f"{doc_id}-segment-{segment_index:04d}",
            case_id=case_id,
            document_id=doc_id,
            segment_index=segment_index,
            page_start=selected_blocks[0]["page"],
            page_end=selected_blocks[-1]["page"],
            page_numbers=[block["page"] for block in selected_blocks],
            chunk_start_index=segment_chunks[0].chunk_index if segment_chunks else None,
            chunk_end_index=segment_chunks[-1].chunk_index if segment_chunks else None,
            text=segment_text,
            text_hash=_text_hash(segment_text),
            heading=heading,
            candidate_date_references=_unique_preserve_order(
                match.group(0) for match in _DATE_REFERENCE_PATTERN.finditer(segment_text)
            )[:10],
            candidate_archive_numbers=_unique_preserve_order(
                match.group(0) for match in _ARCHIVE_NUMBER_PATTERN.finditer(segment_text)
            )[:10],
            candidate_title=heading,
            raw_scope_text=raw_scope_text,
            raw_parcel_references=_parcel_refs_from_text(segment_text),
        )
        segments.append(segment)
        segment_index += 1

        if end >= len(page_blocks):
            break
        next_start = max(start + 1, end - overlap_pages)
        start = next_start

    return segments


def _load_or_build_pipeline_state(
    session: Session,
    case_id: str,
    doc_id: str,
    chunk_list: List[Chunk],
    progress_callback: Optional[ProgressCallback] = None,
) -> AttestPipelineState:
    signature = _source_signature(chunk_list)
    existing = storage_service.load_attest_pipeline_state(session, case_id, doc_id)
    if (
        existing
        and existing.version == ATTEST_PIPELINE_VERSION
        and existing.source_signature == signature
        and existing.segments
    ):
        _emit_progress(
            progress_callback,
            doc_id=doc_id,
            source_type="tinglysningsattest",
            stage="indexed_attest",
            progress=0.15,
            message=f"Genbruger attest-index ({len(existing.segments)} segmenter)",
            segment_count=len(existing.segments),
        )
        return existing

    _emit_progress(
        progress_callback,
        doc_id=doc_id,
        source_type="tinglysningsattest",
        stage="segmenting_attest",
        progress=0.05,
        message="Segmenterer tinglysningsattest",
    )
    segments = build_attest_segments(case_id, doc_id, chunk_list)
    state = AttestPipelineState(
        version=ATTEST_PIPELINE_VERSION,
        case_id=case_id,
        document_id=doc_id,
        source_signature=signature,
        page_count=len({chunk.page for chunk in chunk_list}),
        segments=segments,
        updated_at=datetime.utcnow(),
    )
    storage_service.save_attest_pipeline_state(session, case_id, doc_id, state)
    _emit_progress(
        progress_callback,
        doc_id=doc_id,
        source_type="tinglysningsattest",
        stage="indexed_attest",
        progress=0.2,
        message=f"Attest indekseret i {len(segments)} segmenter",
        segment_count=len(segments),
    )
    return state


def _segment_chunks(chunk_list: List[Chunk], segment: AttestSegment) -> list[Chunk]:
    pages = set(segment.page_numbers)
    return [
        chunk
        for chunk in sorted(chunk_list, key=lambda item: (item.page, item.chunk_index))
        if chunk.page in pages
    ]


def _extract_segment_servitutter(
    segment: AttestSegment,
    chunk_list: List[Chunk],
    case_id: str,
    prompt_template: str,
) -> list[Servitut]:
    prompt = prompt_template.replace("{chunks_text}", _build_chunks_text(chunk_list))
    response_text = generate_text(
        prompt,
        max_tokens=_max_tokens_for_source_type("tinglysningsattest"),
        provider=_resolve_extraction_provider(),
        default_model=_resolve_extraction_model(),
    )
    extracted = _parse_llm_response(response_text)
    return _build_servitutter_from_items(
        extracted,
        case_id=case_id,
        doc_id=segment.document_id,
        source_type="tinglysningsattest",
        chunk_list=chunk_list,
        priority_offset=segment.segment_index * 100,
    )


def _evidence_pages(servitut: Servitut) -> list[int]:
    return sorted({evidence.page for evidence in servitut.evidence})


def _pages_overlap(left: list[int], right: list[int]) -> bool:
    if not left or not right:
        return False
    left_set = set(left)
    right_set = set(right)
    if left_set & right_set:
        return True
    return abs(min(left) - min(right)) <= ATTEST_SEGMENT_OVERLAP_PAGES


def _merge_evidence(left: list[Evidence], right: list[Evidence]) -> list[Evidence]:
    merged: list[Evidence] = []
    seen: set[tuple[str, int, str]] = set()
    for evidence in left + right:
        key = (evidence.document_id, evidence.page, evidence.text_excerpt)
        if key in seen:
            continue
        seen.add(key)
        merged.append(evidence)
    return merged


def _merge_attest_servitut(existing: Servitut, incoming: Servitut) -> Servitut:
    existing_title = (existing.title or "").strip()
    incoming_title = (incoming.title or "").strip()
    existing_scope = (existing.raw_scope_text or "").strip()
    incoming_scope = (incoming.raw_scope_text or "").strip()
    return existing.model_copy(
        update={
            "registered_at": existing.registered_at or incoming.registered_at,
            "archive_number": existing.archive_number
            or incoming.archive_number,
            "title": incoming_title
            if incoming_title and len(incoming_title) > len(existing_title)
            else existing.title,
            "applies_to_parcel_numbers": _unique_preserve_order(
                [*existing.applies_to_parcel_numbers, *incoming.applies_to_parcel_numbers]
            ),
            "raw_parcel_references": _unique_preserve_order(
                [*existing.raw_parcel_references, *incoming.raw_parcel_references]
            ),
            "raw_scope_text": incoming_scope
            if incoming_scope and len(incoming_scope) > len(existing_scope)
            else existing.raw_scope_text,
            "scope_source": "attest",
            "confidence": max(existing.confidence, incoming.confidence),
            "evidence": _merge_evidence(existing.evidence, incoming.evidence),
            "priority": min(existing.priority, incoming.priority),
            "confirmed_by_attest": True,
        }
    )


def _find_merge_candidate(merged: list[Servitut], incoming: Servitut) -> Optional[int]:
    incoming_date = _normalize_key(incoming.date_reference)
    incoming_archive = _normalize_key(incoming.archive_number)
    incoming_title = _normalize_key(incoming.title)
    incoming_pages = _evidence_pages(incoming)

    if incoming_date:
        for idx, existing in enumerate(merged):
            if _normalize_key(existing.date_reference) == incoming_date:
                return idx
    if incoming_archive:
        for idx, existing in enumerate(merged):
            if _normalize_key(existing.archive_number) == incoming_archive:
                return idx
    if incoming_title:
        for idx, existing in enumerate(merged):
            if (
                _normalize_key(existing.title) == incoming_title
                and existing.source_document == incoming.source_document
                and _pages_overlap(_evidence_pages(existing), incoming_pages)
            ):
                return idx
    return None


def merge_attest_servitutter(servitutter: List[Servitut]) -> list[Servitut]:
    merged: list[Servitut] = []
    for servitut in servitutter:
        match_index = _find_merge_candidate(merged, servitut)
        if match_index is None:
            merged.append(
                servitut.model_copy(
                    update={
                        "scope_source": servitut.scope_source or "attest",
                        "confirmed_by_attest": True,
                    }
                )
            )
            continue
        merged[match_index] = _merge_attest_servitut(merged[match_index], servitut)

    merged.sort(
        key=lambda item: (
            _evidence_pages(item)[0] if _evidence_pages(item) else 10**9,
            item.registered_at.isoformat() if item.registered_at else "",
            item.date_reference or "",
            item.title or "",
        )
    )
    return [
        servitut.model_copy(update={"priority": index})
        for index, servitut in enumerate(merged)
    ]


def extract_canonical_from_attest_segments(
    session: Session,
    attest_by_doc: dict[str, List[Chunk]],
    case_id: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> list[Servitut]:
    prompt_template = _load_prompt("tinglysningsattest")
    all_servitutter: list[Servitut] = []
    incomplete_docs: list[dict] = []

    for doc_id, chunk_list in attest_by_doc.items():
        state = _load_or_build_pipeline_state(
            session,
            case_id,
            doc_id,
            chunk_list,
            progress_callback=progress_callback,
        )
        if not state.segments:
            _emit_progress(
                progress_callback,
                doc_id=doc_id,
                source_type="tinglysningsattest",
                stage="completed",
                progress=1.0,
                message="Ingen segmenter fundet i attesten",
                servitut_count=0,
            )
            continue

        failed_segments = 0
        total_segments = len(state.segments)

        for index, segment in enumerate(state.segments, start=1):
            if segment.extraction_status == "completed":
                _emit_progress(
                    progress_callback,
                    doc_id=doc_id,
                    source_type="tinglysningsattest",
                    stage="extracting_attest_segment",
                    progress=0.2 + (index - 1) / max(total_segments, 1) * 0.65,
                    message=(
                        f"Genbruger segment {index}/{total_segments} "
                        f"(sider {segment.page_start}-{segment.page_end})"
                    ),
                    segment_id=segment.segment_id,
                    segment_index=index,
                    segment_count=total_segments,
                    page_start=segment.page_start,
                    page_end=segment.page_end,
                    segment_status="cached",
                )
                continue

            _emit_progress(
                progress_callback,
                doc_id=doc_id,
                source_type="tinglysningsattest",
                stage="extracting_attest_segment",
                progress=0.2 + (index - 1) / max(total_segments, 1) * 0.65,
                message=f"Ekstraherer segment {index}/{total_segments} (sider {segment.page_start}-{segment.page_end})",
                segment_id=segment.segment_id,
                segment_index=index,
                segment_count=total_segments,
                page_start=segment.page_start,
                page_end=segment.page_end,
                segment_status="running",
            )

            segment_chunks = _segment_chunks(chunk_list, segment)
            segment.extraction_attempts += 1
            segment.last_extracted_at = datetime.utcnow()
            try:
                extracted = _extract_segment_servitutter(
                    segment,
                    segment_chunks,
                    case_id,
                    prompt_template,
                )
                segment.extracted_servitutter = [
                    servitut.model_dump(mode="json") for servitut in extracted
                ]
                segment.extraction_status = "completed"
                segment.extraction_error = None
            except Exception as exc:
                failed_segments += 1
                segment.extraction_status = "failed"
                segment.extraction_error = str(exc)
                logger.exception(
                    "Attest segment extraction failed for case=%s doc=%s segment=%s",
                    case_id,
                    doc_id,
                    segment.segment_id,
                )
                _emit_progress(
                    progress_callback,
                    doc_id=doc_id,
                    source_type="tinglysningsattest",
                    stage="attest_segment_failed",
                    progress=0.2 + index / max(total_segments, 1) * 0.65,
                    message=(
                        f"Segment {index}/{total_segments} fejlede "
                        f"(sider {segment.page_start}-{segment.page_end}): {exc}"
                    ),
                    segment_id=segment.segment_id,
                    segment_index=index,
                    segment_count=total_segments,
                    page_start=segment.page_start,
                    page_end=segment.page_end,
                    segment_status="failed",
                )
            finally:
                state.updated_at = datetime.utcnow()
                storage_service.save_attest_pipeline_state(session, case_id, doc_id, state)

        _emit_progress(
            progress_callback,
            doc_id=doc_id,
            source_type="tinglysningsattest",
            stage="merging_attest_segments",
            progress=0.93,
            message=f"Fletter segmentresultater ({total_segments - failed_segments}/{total_segments} klare)",
            segment_count=total_segments,
        )

        if failed_segments:
            incomplete_docs.append(
                {
                    "document_id": doc_id,
                    "failed_segments": failed_segments,
                    "total_segments": total_segments,
                }
            )
            _emit_progress(
                progress_callback,
                doc_id=doc_id,
                source_type="tinglysningsattest",
                stage="failed",
                progress=1.0,
                message=(
                    "Attest-ekstraktion ufuldstændig; canonical liste gemmes ikke "
                    f"({failed_segments}/{total_segments} segmenter fejlede)"
                ),
                segment_count=total_segments,
                failed_segments=failed_segments,
            )
            continue

        segment_servitutter = [
            Servitut(**payload)
            for segment in state.segments
            if segment.extraction_status == "completed"
            for payload in segment.extracted_servitutter
        ]
        merged_doc = merge_attest_servitutter(segment_servitutter)
        all_servitutter.extend(merged_doc)
        _emit_progress(
            progress_callback,
            doc_id=doc_id,
            source_type="tinglysningsattest",
            stage="completed",
            progress=1.0,
            message=(
                f"Færdig: {len(merged_doc)} servitut(ter) "
                f"fra {total_segments - failed_segments}/{total_segments} segmenter"
            ),
            servitut_count=len(merged_doc),
            segment_count=total_segments,
            failed_segments=failed_segments,
        )

    if incomplete_docs:
        raise AttestPipelineIncompleteError(case_id, incomplete_docs)

    return merge_attest_servitutter(all_servitutter)
