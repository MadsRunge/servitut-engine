import json
import re
from typing import List, Optional

from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.servitut import Evidence, Servitut
from app.services.extraction.llm_extractor import _build_chunks_text, _parse_llm_response
from app.services.extraction.merger import _enrich_canonical
from app.services.extraction.progress import ProgressCallback, _emit_progress
from app.services.extraction.prompts import _load_prompt
from app.services.llm_service import generate_text
from app.utils.ids import generate_servitut_id

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_akt_nr(akt_nr: str) -> str:
    """Strip spaces, hyphens and lowercase — used for fuzzy akt_nr comparison."""
    return re.sub(r"[\s\-]", "", akt_nr).lower()


def _find_relevant_chunks(
    chunk_list: List[Chunk],
    date_ref: Optional[str],
    akt_nr: Optional[str],
) -> List[Chunk]:
    """
    Return chunks that mention this servitut's date_reference or akt_nr.
    Falls back to the first three chunks if no keyword match is found.
    """
    needles: list[str] = []
    if date_ref:
        # Normalised: strip internal spaces/hyphens for loose substring matching
        needles.append(re.sub(r"[\s\-]", "", date_ref).lower())
    if akt_nr:
        needles.append(_normalize_akt_nr(akt_nr))

    if needles:
        matching = [
            c for c in chunk_list
            if any(n in re.sub(r"[\s\-]", "", c.text).lower() for n in needles)
        ]
        if matching:
            return matching[:3]

    return chunk_list[:3]


def _make_akt_evidence(
    chunk_list: List[Chunk],
    date_ref: Optional[str] = None,
    akt_nr: Optional[str] = None,
) -> List[Evidence]:
    relevant = _find_relevant_chunks(chunk_list, date_ref, akt_nr)
    return [
        Evidence(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            page=c.page,
            text_excerpt=c.text[:300],
        )
        for c in relevant
    ]


def _build_canonical_json(canonical_list: List[Servitut]) -> str:
    items = [
        {
            "date_reference": s.date_reference,
            "akt_nr": s.akt_nr,
            "title": s.title,
        }
        for s in canonical_list
    ]
    return json.dumps(items, ensure_ascii=False, indent=2)


def _coerce_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip().lower()]
    return []


def _resolve_canonical_key(
    item: dict,
    canonical_by_date: dict[str, str],
    canonical_by_akt: dict[str, str],
) -> Optional[str]:
    """
    Map an LLM-returned enrichment item back to a canonical date_reference key.

    Priority:
      1. Normalised akt_nr (primary — survives minor reformatting by the LLM)
      2. Exact date_reference match (secondary)
    Returns None if no canonical is found.
    """
    item_akt = item.get("akt_nr")
    if item_akt:
        key = _normalize_akt_nr(item_akt)
        canonical_key = canonical_by_akt.get(key)
        if canonical_key:
            return canonical_key

    item_date = item.get("date_reference") or ""
    return canonical_by_date.get(item_date)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _enrich_from_doc(
    doc_id: str,
    chunk_list: List[Chunk],
    canonical_list: List[Servitut],
    all_matrikler: List[str],
    progress_callback: Optional[ProgressCallback],
) -> List[dict]:
    """One LLM call per akt: ask which canonical servitutter it contains."""
    _emit_progress(
        progress_callback,
        doc_id=doc_id,
        source_type="akt",
        stage="running",
        progress=0.2,
        message="Målrettet berigelse",
    )

    prompt_template = _load_prompt("enrich_servitut")
    canonical_json = _build_canonical_json(canonical_list)
    chunks_text = _build_chunks_text(chunk_list)
    prompt = (
        prompt_template
        .replace("{canonical_json}", canonical_json)
        .replace("{all_matrikler_json}", json.dumps(all_matrikler, ensure_ascii=False))
        .replace("{chunks_text}", chunks_text)
    )

    try:
        _emit_progress(
            progress_callback,
            doc_id=doc_id,
            source_type="akt",
            stage="requesting",
            progress=0.5,
            message="Sender LLM-kald",
        )
        response_text = generate_text(prompt, max_tokens=4096)
        items = _parse_llm_response(response_text)
        _emit_progress(
            progress_callback,
            doc_id=doc_id,
            source_type="akt",
            stage="completed",
            progress=1.0,
            message=f"Færdig: {len(items)} match(es)",
            servitut_count=len(items),
        )
        return items
    except Exception as exc:
        logger.error(f"Enrichment LLM error for doc {doc_id}: {exc}")
        _emit_progress(
            progress_callback,
            doc_id=doc_id,
            source_type="akt",
            stage="failed",
            progress=1.0,
            message=f"Fejl: {exc}",
        )
        return []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def enrich_canonical_list(
    canonical_list: List[Servitut],
    akt_chunks_by_doc: dict[str, List[Chunk]],
    case_id: str,
    all_matrikler: Optional[List[str]] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[Servitut]:
    """
    Canonical-driven enrichment.

    For each akt document, one LLM call returns the subset of canonical
    servitutter it describes.  Matching uses akt_nr (normalised) first,
    then date_reference.  Evidence chunks are chosen by keyword proximity
    to the matched servitut, not positionally.
    """
    if not akt_chunks_by_doc or not canonical_list:
        return canonical_list

    all_matrikler = all_matrikler or []

    # Build two lookup tables: date_reference → canonical_date_key
    #                          normalised_akt_nr → canonical_date_key
    canonical_by_date: dict[str, str] = {
        (s.date_reference or ""): (s.date_reference or "")
        for s in canonical_list
    }
    canonical_by_akt: dict[str, str] = {
        _normalize_akt_nr(s.akt_nr): (s.date_reference or "")
        for s in canonical_list
        if s.akt_nr
    }
    # key (canonical date_reference) → (best item dict, doc_id, chunk_list)
    best_by_key: dict[str, tuple[dict, str, List[Chunk]]] = {}

    for doc_id, chunk_list in akt_chunks_by_doc.items():
        _emit_progress(
            progress_callback,
            doc_id=doc_id,
            source_type="akt",
            stage="queued",
            progress=0.0,
            message="Sat i kø",
        )

        items = _enrich_from_doc(
            doc_id,
            chunk_list,
            canonical_list,
            all_matrikler,
            progress_callback,
        )

        for item in items:
            key = _resolve_canonical_key(item, canonical_by_date, canonical_by_akt)
            if key is None:
                logger.debug(
                    f"Enrichment item not matched to any canonical "
                    f"(date={item.get('date_reference')!r}, akt_nr={item.get('akt_nr')!r})"
                )
                continue
            item_conf = float(item.get("confidence", 0.5) or 0.5)
            existing = best_by_key.get(key)
            existing_conf = float(existing[0].get("confidence", 0) if existing else 0)
            if existing is None or item_conf > existing_conf:
                best_by_key[key] = (item, doc_id, chunk_list)

    # Apply enrichments
    result: List[Servitut] = []
    matched = 0
    for canonical in canonical_list:
        key = canonical.date_reference or ""
        entry = best_by_key.get(key)
        if entry:
            item, doc_id, chunk_list = entry
            enriched_date = item.get("date_reference", canonical.date_reference)
            enriched_akt_nr = item.get("akt_nr", canonical.akt_nr)
            applies_to_matrikler = _coerce_str_list(item.get("applies_to_matrikler"))
            akt_srv = Servitut(
                servitut_id=generate_servitut_id(),
                case_id=case_id,
                source_document=doc_id,
                date_reference=enriched_date,
                akt_nr=enriched_akt_nr,
                title=item.get("title", canonical.title),
                summary=item.get("summary"),
                beneficiary=item.get("beneficiary"),
                disposition_type=item.get("disposition_type"),
                legal_type=item.get("legal_type"),
                construction_relevance=bool(item.get("construction_relevance", False)),
                byggeri_markering=item.get("byggeri_markering"),
                action_note=item.get("action_note"),
                applies_to_matrikler=applies_to_matrikler,
                scope_basis=item.get("scope_basis"),
                scope_confidence=item.get("scope_confidence"),
                confidence=float(item.get("confidence", 0.5) or 0.5),
                evidence=_make_akt_evidence(chunk_list, enriched_date, enriched_akt_nr),
            )
            result.append(_enrich_canonical(canonical, akt_srv))
            matched += 1
        else:
            result.append(canonical)

    logger.info(f"Enrichment færdig: {matched}/{len(canonical_list)} servitutter beriget fra akter")
    return result
