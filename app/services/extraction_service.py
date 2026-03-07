from typing import List, Optional

from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.servitut import Servitut
from app.services.extraction import (
    ProgressCallback,
    _dedup_akt_servitutter,
    _extract_date_components,
    _extract_document_servitutter,
    _extract_from_doc_chunks,
    _load_prompt,
    _merge_servitutter,
    _parse_llm_response,
    _prescreeen_chunks,
    _servitut_matches,
)
from app.services import storage_service

logger = get_logger(__name__)


def extract_servitutter(
    chunks: List[Chunk],
    case_id: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[Servitut]:
    """
    To-pas udtræk:
      Pas 1: Udtræk canonical liste fra tinglysningsattest (løbenumre som nøgle)
      Pas 2: Udtræk detaljer fra individuelle akter
      Merge: Berig canonical med akt-detaljer, kassér duplikater

    Fallback: Hvis ingen tinglysningsattest, udtræk fra alle akter som før.
    """
    if not chunks:
        return []

    # Klassificér chunks efter dokumenttype
    doc_ids = list(dict.fromkeys(c.document_id for c in chunks))
    doc_types: dict[str, str] = {}
    for doc_id in doc_ids:
        doc = storage_service.load_document(case_id, doc_id)
        doc_types[doc_id] = doc.document_type if doc else "akt"

    attest_chunks: list[Chunk] = []
    akt_chunks: list[Chunk] = []
    for chunk in chunks:
        if doc_types.get(chunk.document_id) == "tinglysningsattest":
            attest_chunks.append(chunk)
        else:
            akt_chunks.append(chunk)

    # --- Fallback: ingen tinglysningsattest ---
    if not attest_chunks:
        logger.info("Ingen tinglysningsattest — udtræk fra alle akter direkte")
        relevant = _prescreeen_chunks(akt_chunks)
        if not relevant:
            return []
        doc_chunks: dict[str, list[Chunk]] = {}
        for c in relevant:
            doc_chunks.setdefault(c.document_id, []).append(c)
        akt_list = _extract_from_doc_chunks(
            doc_chunks,
            case_id,
            "akt",
            progress_callback=progress_callback,
        )
        return _dedup_akt_servitutter(akt_list)

    # --- Pas 1: Tinglysningsattest ---
    logger.info(f"Pas 1: Udtræk fra tinglysningsattest ({len(attest_chunks)} chunks)")
    attest_by_doc: dict[str, list[Chunk]] = {}
    for c in attest_chunks:
        attest_by_doc.setdefault(c.document_id, []).append(c)
    canonical_list = _extract_from_doc_chunks(
        attest_by_doc,
        case_id,
        "tinglysningsattest",
        progress_callback=progress_callback,
    )
    logger.info(f"Canonical liste: {len(canonical_list)} servitutter")

    if not akt_chunks:
        return canonical_list

    # --- Pas 2: Akter ---
    logger.info(f"Pas 2: Udtræk fra akter ({len(akt_chunks)} chunks)")
    relevant_akt = _prescreeen_chunks(akt_chunks)
    if relevant_akt:
        akt_by_doc: dict[str, list[Chunk]] = {}
        for c in relevant_akt:
            akt_by_doc.setdefault(c.document_id, []).append(c)
        akt_list = _extract_from_doc_chunks(
            akt_by_doc,
            case_id,
            "akt",
            progress_callback=progress_callback,
        )
        logger.info(f"Akt-udtræk: {len(akt_list)} servitutter")
    else:
        akt_list = []

    # --- Merge ---
    return _merge_servitutter(canonical_list, akt_list)
