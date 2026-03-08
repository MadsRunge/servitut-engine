import json
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


def _make_akt_evidence(chunk_list: List[Chunk]) -> List[Evidence]:
    return [
        Evidence(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            page=c.page,
            text_excerpt=c.text[:300],
        )
        for c in chunk_list[:3]
    ]


def _enrich_from_doc(
    doc_id: str,
    chunk_list: List[Chunk],
    canonical_list: List[Servitut],
    progress_callback: Optional[ProgressCallback],
) -> List[dict]:
    """One LLM call per akt: ask which canonical servitutter it contains and return enriched dicts."""
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


def enrich_canonical_list(
    canonical_list: List[Servitut],
    akt_chunks_by_doc: dict[str, List[Chunk]],
    case_id: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[Servitut]:
    """
    Canonical-driven enrichment.

    For each akt document, call LLM once asking which canonical servitutter
    it describes. Keep best enrichment (by confidence) per canonical entry.
    """
    if not akt_chunks_by_doc or not canonical_list:
        return canonical_list

    # date_reference is our primary key from attest
    canonical_by_key: dict[str, Servitut] = {
        (s.date_reference or ""): s for s in canonical_list
    }

    # Accumulate best enrichment dict per canonical key
    best_by_key: dict[str, tuple[dict, str, List[Chunk]]] = {}  # key → (item, doc_id, chunks)

    for doc_id, chunk_list in akt_chunks_by_doc.items():
        _emit_progress(
            progress_callback,
            doc_id=doc_id,
            source_type="akt",
            stage="queued",
            progress=0.0,
            message="Sat i kø",
        )

        items = _enrich_from_doc(doc_id, chunk_list, canonical_list, progress_callback)

        for item in items:
            key = item.get("date_reference") or ""
            if key not in canonical_by_key:
                logger.debug(f"Enrichment key not in canonical list: {key!r}")
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
            akt_srv = Servitut(
                servitut_id=generate_servitut_id(),
                case_id=case_id,
                source_document=doc_id,
                date_reference=item.get("date_reference", canonical.date_reference),
                akt_nr=item.get("akt_nr", canonical.akt_nr),
                title=item.get("title", canonical.title),
                summary=item.get("summary"),
                beneficiary=item.get("beneficiary"),
                disposition_type=item.get("disposition_type"),
                legal_type=item.get("legal_type"),
                construction_relevance=bool(item.get("construction_relevance", False)),
                byggeri_markering=item.get("byggeri_markering"),
                action_note=item.get("action_note"),
                confidence=float(item.get("confidence", 0.5) or 0.5),
                evidence=_make_akt_evidence(chunk_list),
            )
            result.append(_enrich_canonical(canonical, akt_srv))
            matched += 1
        else:
            result.append(canonical)

    logger.info(f"Enrichment færdig: {matched}/{len(canonical_list)} servitutter beriget fra akter")
    return result
