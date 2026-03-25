"""Ny clean attest extraction path.

Arkitektur:
  chunks
    → extract_servitutter_section_text()   # tekst-niveau split på char-position
    → split_into_candidate_blocks()        # deterministisk per-entry splitting
    → [per block] _extract_from_candidate_block_llm()  # LLM med minimal kontekst
    → merge_candidate_servitutter()        # ny dedup-logik for candidate path

Erstatter den gamle page-window → classify → assemble → fanout pipeline.
"""
from __future__ import annotations

import hashlib
import re
from typing import List, Optional

from app.core.logging import get_logger
from app.models.attest import AttestCandidateBlock
from app.models.chunk import Chunk
from app.models.servitut import Evidence, Servitut
from app.services.extraction.llm_extractor import (
    _build_servitutter_from_items,
    _max_tokens_for_source_type,
    _parse_llm_response,
    _resolve_extraction_model,
    _resolve_extraction_provider,
)
from app.services.extraction.normalization import (
    coerce_optional_int,
    coerce_optional_str,
    parse_registered_at,
)
from app.services.extraction.prompts import _load_prompt
from app.services.llm_service import generate_text

logger = get_logger(__name__)

_SECTION_HEADERS: set[str] = {
    "adkomster",
    "hæftelser",
    "servitutter",
    "øvrige oplysninger",
}

_DATE_REFERENCE_PATTERN = re.compile(r"\b\d{2}\.\d{2}\.\d{4}-[0-9A-Za-z./-]+\b")
_ARCHIVE_NUMBER_PATTERN = re.compile(
    r"\b(?:\d+\s*[A-ZÆØÅ]\s*-?\s*\d+|[A-ZÆØÅ]-\d+|\d+\s*[A-ZÆØÅ]\s*\d+)\b"
)

# En candidate block begynder ved en "Dokument:" standalone linje.
# Lookahead bruges så splittet ikke fjerner den matchede linje.
_CANDIDATE_BOUNDARY = re.compile(r"(?=^\s*Dokument\s*:\s*$)", re.MULTILINE)

# Blokke med færre end disse tegn (ekskl. whitespace) anses for at være
# section-header-linje alene og skippes.
_MIN_CANDIDATE_NET_CHARS = 30


def _normalize_merge_key(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = re.sub(r"[^0-9a-z]+", "", value.lower())
    return normalized or None


class ServitutterSectionNotFoundError(RuntimeError):
    """Kastes når section-headers er fundet, men Servitutter-sektionen mangler.

    Betyder: attesten har en struktureret sektion-inddeling, men
    Servitutter-sektionen er ikke blandt dem (OCR-fejl, forkert dokument, o.l.).
    """

    def __init__(self, detected_sections: list[str]) -> None:
        self.detected_sections = detected_sections
        super().__init__(
            f"Servitutter-sektion ikke fundet i attesten. "
            f"Detekterede sektioner: {detected_sections}"
        )


# ---------------------------------------------------------------------------
# Interne hjælpefunktioner
# ---------------------------------------------------------------------------

def _block_id(doc_id: str, char_start: int) -> str:
    payload = f"{doc_id}:{char_start}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _build_full_text(
    chunks: List[Chunk],
) -> tuple[str, list[tuple[int, int, Chunk]]]:
    """Byg samlet dokumenttekst og char→chunk-mapping.

    Returnerer:
      full_text           — samlet tekst for alle chunks
      char_chunk_map      — liste af (char_start, char_end, chunk) sorteret efter position
    """
    ordered = sorted(chunks, key=lambda c: (c.page, c.chunk_index))
    parts: list[str] = []
    char_chunk_map: list[tuple[int, int, Chunk]] = []
    pos = 0
    for chunk in ordered:
        text = chunk.text or ""
        char_chunk_map.append((pos, pos + len(text), chunk))
        parts.append(text)
        pos += len(text) + 1  # +1 for "\n" separator
    full_text = "\n".join(parts)
    return full_text, char_chunk_map


def _find_section_boundaries(full_text: str) -> dict[str, int]:
    """Find tegnposition for kendte section-headers.

    Returnerer kun headers der faktisk er fundet.
    Matcher kun standalone linjer (strip + lower exact match).
    """
    found: dict[str, int] = {}
    lines = full_text.splitlines(keepends=True)
    pos = 0
    for line in lines:
        stripped = line.strip().lower()
        if stripped in _SECTION_HEADERS and stripped not in found:
            found[stripped] = pos
        pos += len(line)
    return found


def _extract_labeled_value(text: str, label: str) -> Optional[str]:
    lines = text.splitlines()
    target = label.strip().lower().rstrip(":")
    for index, line in enumerate(lines):
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered == target or lowered == f"{target}:":
            for next_line in lines[index + 1 :]:
                next_value = next_line.strip()
                if next_value:
                    return next_value
            return None
        if lowered.startswith(f"{target}:"):
            value = stripped.split(":", 1)[1].strip()
            if value:
                return value
            for next_line in lines[index + 1 :]:
                next_value = next_line.strip()
                if next_value:
                    return next_value
            return None
    return None


def _pages_for_char_range(
    char_start: int,
    char_end: int,
    char_chunk_map: list[tuple[int, int, Chunk]],
) -> list[int]:
    """Find sidenumre der overlapper med [char_start, char_end)."""
    pages: list[int] = []
    for cstart, cend, chunk in char_chunk_map:
        if cend <= char_start:
            continue
        if cstart >= char_end:
            break
        if chunk.page not in pages:
            pages.append(chunk.page)
    return pages


def _section_char_map(
    section_start: int,
    section_end: int,
    char_chunk_map: list[tuple[int, int, Chunk]],
) -> list[tuple[int, int, Chunk]]:
    """Udtræk char_chunk_map-entries der overlapper med [section_start, section_end)."""
    return [
        (max(cstart, section_start), min(cend, section_end), chunk)
        for cstart, cend, chunk in char_chunk_map
        if cstart < section_end and cend > section_start
    ]


# ---------------------------------------------------------------------------
# Offentlige/interne API-funktioner
# ---------------------------------------------------------------------------

def extract_servitutter_section_text(
    chunks: List[Chunk],
) -> tuple[str, list[tuple[int, int, Chunk]]]:
    """Udtræk tekst og char-mapping for Servitutter-sektionen.

    Fail-logik:
    - Ingen section-headers fundet → returnér alt (Aalborg-fallback)
    - Headers fundet men Servitutter mangler → raise ServitutterSectionNotFoundError
    - Servitutter fundet → returnér kun dens tekst (char-niveau)
    """
    if not chunks:
        return "", []

    full_text, char_chunk_map = _build_full_text(chunks)
    boundaries = _find_section_boundaries(full_text)

    if not boundaries:
        logger.warning(
            "extract_servitutter_section_text: ingen section-headers fundet "
            "(%d chunks) — returnerer alt (backward compat fallback)",
            len(chunks),
        )
        return full_text, char_chunk_map

    if "servitutter" not in boundaries:
        detected = sorted(boundaries.keys())
        raise ServitutterSectionNotFoundError(detected)

    servitutter_start = boundaries["servitutter"]

    # Find næste sections start (sorteret efter tegnposition)
    later_positions = [
        pos for name, pos in boundaries.items()
        if pos > servitutter_start
    ]
    servitutter_end = min(later_positions) if later_positions else len(full_text)

    section_text = full_text[servitutter_start:servitutter_end]
    section_map = _section_char_map(servitutter_start, servitutter_end, char_chunk_map)

    logger.info(
        "extract_servitutter_section_text: Servitutter-sektion %d–%d tegn "
        "(%d/%d tegn af hele attesten)",
        servitutter_start,
        servitutter_end,
        len(section_text),
        len(full_text),
    )
    return section_text, section_map


def split_into_candidate_blocks(
    section_text: str,
    char_chunk_map: list[tuple[int, int, Chunk]],
    case_id: str,
    doc_id: str,
) -> List[AttestCandidateBlock]:
    """Split Servitutter-sektion i per-entry candidate blocks.

    Splitter på standalone "Dokument:"-linjer som reelt er entry-separator
    i tinglysningsattest-OCR.

    Blokke der kun indeholder section-headeren eller er for korte skippes.
    """
    if not section_text.strip():
        return []

    # Find absolutte char-positioner for kandidat-grænser
    # section_char_map er offset relativt til full_text; vi arbejder med section_text
    # direkte her, og beregner sider via char_chunk_map der er fuldt-tekstbaseret.
    # Afstanden fra full_text-start til section_text-start:
    section_offset = char_chunk_map[0][0] if char_chunk_map else 0

    raw_parts: list[tuple[int, int]] = []
    last = 0
    for m in _CANDIDATE_BOUNDARY.finditer(section_text):
        boundary = m.start()
        if boundary > last:
            raw_parts.append((last, boundary))
        last = boundary
    raw_parts.append((last, len(section_text)))

    blocks: list[AttestCandidateBlock] = []
    for rel_start, rel_end in raw_parts:
        text = section_text[rel_start:rel_end]
        net = text.strip()
        # Skip blokke der kun er section-header eller for korte
        if len(net) < _MIN_CANDIDATE_NET_CHARS:
            logger.debug(
                "split_into_candidate_blocks: skip kort blok (%d tegn): %r",
                len(net),
                net[:60],
            )
            continue

        abs_start = section_offset + rel_start
        abs_end = section_offset + rel_end
        pages = _pages_for_char_range(abs_start, abs_end, char_chunk_map)

        date_refs = list(dict.fromkeys(
            m.group(0) for m in _DATE_REFERENCE_PATTERN.finditer(text)
        ))
        archive_nums = list(dict.fromkeys(
            m.group(0) for m in _ARCHIVE_NUMBER_PATTERN.finditer(text)
        ))

        block = AttestCandidateBlock(
            block_id=_block_id(doc_id, abs_start),
            case_id=case_id,
            document_id=doc_id,
            text=text,
            page_numbers=pages,
            candidate_date_references=date_refs,
            candidate_archive_numbers=archive_nums,
        )
        blocks.append(block)

    logger.info(
        "split_into_candidate_blocks: %d candidate blocks fra %d tegn",
        len(blocks),
        len(section_text),
    )
    return blocks


def _build_evidence_from_block(block: AttestCandidateBlock) -> List[Evidence]:
    """Lav minimal evidence for en candidate block (ingen chunks tilgængelige)."""
    # Evidence med page_numbers og kort excerpt
    evidence = []
    for page in block.page_numbers[:3]:
        evidence.append(
            Evidence(
                chunk_id=block.block_id,
                document_id=block.document_id,
                page=page,
                text_excerpt=block.text[:300],
            )
        )
    return evidence


def _merge_evidence(left: List[Evidence], right: List[Evidence]) -> List[Evidence]:
    merged: list[Evidence] = []
    seen: set[tuple[str, int, str]] = set()
    for evidence in left + right:
        key = (evidence.document_id, evidence.page, evidence.text_excerpt)
        if key in seen:
            continue
        seen.add(key)
        merged.append(evidence)
    return merged


def _merge_string_lists(left: list[str], right: list[str]) -> list[str]:
    merged: list[str] = []
    for item in left + right:
        if item and item not in merged:
            merged.append(item)
    return merged


def _merge_priority(existing: int, incoming: int) -> int:
    if existing > 0 and incoming > 0:
        return min(existing, incoming)
    if existing > 0:
        return existing
    if incoming > 0:
        return incoming
    return min(existing, incoming)


def _merge_servitut(existing: Servitut, incoming: Servitut) -> Servitut:
    existing_title = (existing.title or "").strip()
    incoming_title = (incoming.title or "").strip()
    existing_summary = (existing.summary or "").strip()
    incoming_summary = (incoming.summary or "").strip()
    existing_scope = (existing.raw_scope_text or "").strip()
    incoming_scope = (incoming.raw_scope_text or "").strip()
    return existing.model_copy(
        update={
            "priority": _merge_priority(existing.priority, incoming.priority),
            "date_reference": existing.date_reference or incoming.date_reference,
            "registered_at": existing.registered_at or incoming.registered_at,
            "archive_number": existing.archive_number or incoming.archive_number,
            "title": incoming_title
            if incoming_title and len(incoming_title) > len(existing_title)
            else existing.title,
            "summary": incoming_summary
            if incoming_summary and len(incoming_summary) > len(existing_summary)
            else existing.summary,
            "beneficiary": existing.beneficiary or incoming.beneficiary,
            "disposition_type": existing.disposition_type or incoming.disposition_type,
            "legal_type": existing.legal_type or incoming.legal_type,
            "construction_relevance": existing.construction_relevance
            or incoming.construction_relevance,
            "construction_impact": existing.construction_impact or incoming.construction_impact,
            "action_note": existing.action_note or incoming.action_note,
            "applies_to_parcel_numbers": _merge_string_lists(
                existing.applies_to_parcel_numbers,
                incoming.applies_to_parcel_numbers,
            ),
            "raw_parcel_references": _merge_string_lists(
                existing.raw_parcel_references,
                incoming.raw_parcel_references,
            ),
            "raw_scope_text": incoming_scope
            if incoming_scope and len(incoming_scope) > len(existing_scope)
            else existing.raw_scope_text,
            "scope_source": existing.scope_source or incoming.scope_source,
            "scope_basis": existing.scope_basis or incoming.scope_basis,
            "scope_confidence": existing.scope_confidence or incoming.scope_confidence,
            "confidence": max(existing.confidence, incoming.confidence),
            "evidence": _merge_evidence(existing.evidence, incoming.evidence),
            "flags": _merge_string_lists(existing.flags, incoming.flags),
            "confirmed_by_attest": True,
        }
    )


def merge_candidate_servitutter(servitutter: List[Servitut]) -> List[Servitut]:
    merged: list[Servitut] = []
    for servitut in servitutter:
        incoming_date = _normalize_merge_key(servitut.date_reference)
        incoming_archive = _normalize_merge_key(servitut.archive_number)
        incoming_title = _normalize_merge_key(servitut.title)
        match_index: Optional[int] = None
        for index, existing in enumerate(merged):
            existing_date = _normalize_merge_key(existing.date_reference)
            if incoming_date and existing_date == incoming_date:
                match_index = index
                break
            existing_archive = _normalize_merge_key(existing.archive_number)
            if (
                incoming_archive
                and existing_archive == incoming_archive
                and existing.source_document == servitut.source_document
            ):
                match_index = index
                break
            existing_title = _normalize_merge_key(existing.title)
            if (
                incoming_title
                and existing_title == incoming_title
                and existing.source_document == servitut.source_document
                and existing.priority == servitut.priority
                and not (existing_date and incoming_date and existing_date != incoming_date)
            ):
                match_index = index
                break

        if match_index is None:
            merged.append(servitut.model_copy(update={"confirmed_by_attest": True}))
            continue
        merged[match_index] = _merge_servitut(merged[match_index], servitut)

    merged.sort(
        key=lambda item: (
            item.priority if item.priority > 0 else 10**9,
            item.registered_at.isoformat() if item.registered_at else "",
            item.date_reference or "",
            item.title or "",
        )
    )
    return merged


def _inject_candidate_defaults(
    extracted: list[dict],
    block: AttestCandidateBlock,
) -> list[dict]:
    priority_value = coerce_optional_int(_extract_labeled_value(block.text, "Prioritet"))
    date_reference_value = coerce_optional_str(
        _extract_labeled_value(block.text, "Dato/løbenummer")
    )
    archive_number_value = coerce_optional_str(_extract_labeled_value(block.text, "Akt nr"))

    if date_reference_value is None and len(block.candidate_date_references) == 1:
        date_reference_value = block.candidate_date_references[0]
    if archive_number_value is None and len(block.candidate_archive_numbers) == 1:
        archive_number_value = block.candidate_archive_numbers[0]

    enriched: list[dict] = []
    for item in extracted:
        enriched_item = dict(item)
        if priority_value is not None and coerce_optional_int(enriched_item.get("priority")) is None:
            enriched_item["priority"] = priority_value
        if date_reference_value and not coerce_optional_str(enriched_item.get("date_reference")):
            enriched_item["date_reference"] = date_reference_value
        if archive_number_value and not coerce_optional_str(enriched_item.get("archive_number")):
            enriched_item["archive_number"] = archive_number_value
        if enriched_item.get("registered_at") in (None, "") and enriched_item.get("date_reference"):
            enriched_item["registered_at"] = parse_registered_at(
                None,
                coerce_optional_str(enriched_item.get("date_reference")),
            )
        enriched.append(enriched_item)
    return enriched


def _extract_from_candidate_block_llm(
    block: AttestCandidateBlock,
    prompt_template: str,
) -> List[Servitut]:
    """LLM semantic extraction for én candidate block.

    LLM'en modtager kun candidate block-teksten — ikke hele attesten.
    Blokke med `is_servitut_candidate: false` ekskluderes fra output.
    """
    prompt = prompt_template.replace("{candidate_text}", block.text)
    try:
        response_text = generate_text(
            prompt,
            max_tokens=_max_tokens_for_source_type("tinglysningsattest_candidate"),
            provider=_resolve_extraction_provider(),
            default_model=_resolve_extraction_model(),
        )
    except Exception as exc:
        logger.error(
            "LLM-kald fejlede for candidate block %s (doc=%s): %s",
            block.block_id,
            block.document_id,
            exc,
        )
        return []

    extracted = _parse_llm_response(response_text)
    if not extracted:
        return []
    extracted = _inject_candidate_defaults(extracted, block)

    # Filtrér blokke som LLM eksplicit afviser
    accepted = [
        item for item in extracted
        if item.get("is_servitut_candidate", True)
    ]
    if len(accepted) < len(extracted):
        rejected_count = len(extracted) - len(accepted)
        logger.info(
            "LLM afviste %d/%d items fra block %s: %s",
            rejected_count,
            len(extracted),
            block.block_id,
            [item.get("rejection_reason") for item in extracted if not item.get("is_servitut_candidate", True)],
        )

    if not accepted:
        return []

    # Genbrug eksisterende build-funktion; chunk_list er tom da vi kun har block-tekst
    # Evidence sættes manuelt fra block.page_numbers
    evidence = _build_evidence_from_block(block)
    servitutter = _build_servitutter_from_items(
        accepted,
        case_id=block.case_id,
        doc_id=block.document_id,
        source_type="tinglysningsattest",
        chunk_list=[],  # ingen individuelle chunks tilgængelige her
    )
    patched: list[Servitut] = []
    # Patch evidence på alle entries (build_servitutter_from_items finder ingen chunks)
    for servitut in servitutter:
        if not servitut.evidence:
            servitut = servitut.model_copy(update={"evidence": evidence})
        patched.append(servitut)
    return patched


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_attest_extraction(
    chunks: List[Chunk],
    case_id: str,
    doc_id: str,
    *,
    prompt_template: Optional[str] = None,
) -> List[Servitut]:
    """Ny clean extraction path for tinglysningsattest.

    1. Tekst-niveau sektion-split (char-position, ikke sidenummer)
    2. Deterministisk candidate block-splitting
    3. LLM semantic extraction per candidate block
    4. Merge/dedup

    Kaster ServitutterSectionNotFoundError hvis section-headers er fundet
    men Servitutter-sektionen mangler.
    """
    if not chunks:
        return []

    template = prompt_template or _load_prompt("attest_candidate")

    section_text, section_char_map = extract_servitutter_section_text(chunks)
    if not section_text.strip():
        logger.warning(
            "run_attest_extraction: tom section-tekst for doc=%s — ingen servitutter",
            doc_id,
        )
        return []

    candidates = split_into_candidate_blocks(section_text, section_char_map, case_id, doc_id)
    if not candidates:
        logger.warning(
            "run_attest_extraction: ingen candidate blocks fundet for doc=%s",
            doc_id,
        )
        return []

    all_servitutter: list[Servitut] = []
    for block in candidates:
        entries = _extract_from_candidate_block_llm(block, template)
        all_servitutter.extend(entries)

    result = merge_candidate_servitutter(all_servitutter)
    logger.info(
        "run_attest_extraction: doc=%s → %d candidate blocks → %d servitutter",
        doc_id,
        len(candidates),
        len(result),
    )
    return result
