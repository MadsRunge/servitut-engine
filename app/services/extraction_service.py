from typing import List, Optional

from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.servitut import Servitut
from app.services.extraction import (
    ProgressCallback,
    _dedup_akt_servitutter,
    _extract_document_servitutter,
    _extract_from_doc_chunks,
    _prescreeen_chunks,
    enrich_canonical_list,
)
from app.services import matrikel_service, storage_service
from app.services.extraction.enricher import (
    build_scoring_signals,
    score_chunks,
    select_candidate_chunks,
)

logger = get_logger(__name__)


def _load_documents_by_id(case_id: str, doc_ids: list[str]) -> dict[str, Document]:
    requested = set(doc_ids)
    if not requested:
        return {}
    return {
        doc.document_id: doc
        for doc in storage_service.list_documents(case_id)
        if doc.document_id in requested
    }


def extract_servitutter(
    chunks: List[Chunk],
    case_id: str,
    progress_callback: Optional[ProgressCallback] = None,
    cached_canonical: Optional[List[Servitut]] = None,
) -> List[Servitut]:
    """
    To-pas udtræk:
      Pas 1: Udtræk canonical liste fra tinglysningsattest (løbenumre som nøgle)
             — springes over hvis cached_canonical er givet
      Pas 2: Udtræk detaljer fra individuelle akter
      Merge: Berig canonical med akt-detaljer, kassér duplikater

    Fallback: Hvis ingen tinglysningsattest og ingen cached_canonical,
              udtræk fra alle akter direkte.
    """
    if not chunks:
        return []

    # Klassificér chunks efter dokumenttype
    doc_ids = list(dict.fromkeys(c.document_id for c in chunks))
    documents_by_id = _load_documents_by_id(case_id, doc_ids)
    doc_types: dict[str, str] = {}
    for doc_id in doc_ids:
        doc = documents_by_id.get(doc_id)
        doc_types[doc_id] = doc.document_type if doc else "akt"

    attest_chunks: list[Chunk] = []
    akt_chunks: list[Chunk] = []
    for chunk in chunks:
        if doc_types.get(chunk.document_id) == "tinglysningsattest":
            attest_chunks.append(chunk)
        else:
            akt_chunks.append(chunk)

    # --- Fallback: ingen tinglysningsattest og ingen cache ---
    if not attest_chunks and not cached_canonical:
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

    # --- Pas 1: Tinglysningsattest (spring over hvis cache er tilgængelig) ---
    if cached_canonical:
        logger.info(f"Pas 1: Bruger cached canonical liste ({len(cached_canonical)} servitutter) — springer LLM-kald over")
        canonical_list = cached_canonical
        attest_by_doc: dict[str, list[Chunk]] = {}
        for c in attest_chunks:
            attest_by_doc.setdefault(c.document_id, []).append(c)
    else:
        logger.info(f"Pas 1: Udtræk fra tinglysningsattest ({len(attest_chunks)} chunks)")
        attest_by_doc = {}
        for c in attest_chunks:
            attest_by_doc.setdefault(c.document_id, []).append(c)
        canonical_list = _extract_from_doc_chunks(
            attest_by_doc,
            case_id,
            "tinglysningsattest",
            progress_callback=progress_callback,
        )
    logger.info(f"Canonical liste: {len(canonical_list)} servitutter")

    case = matrikel_service.sync_case_matrikler(case_id, attest_by_doc.keys())
    all_matrikler = [matrikel.matrikelnummer for matrikel in case.matrikler] if case else []

    if not akt_chunks:
        return canonical_list

    # --- Pas 2: Canonical-driven berigelse fra akter ---
    logger.info(f"Pas 2: Canonical-driven berigelse fra akter ({len(akt_chunks)} chunks)")
    akt_by_doc: dict[str, list[Chunk]] = {}
    for c in akt_chunks:
        akt_by_doc.setdefault(c.document_id, []).append(c)

    doc_filename_by_id: dict[str, str] = {}
    for doc_id in akt_by_doc:
        doc = documents_by_id.get(doc_id)
        if doc and doc.filename:
            doc_filename_by_id[doc_id] = doc.filename

    return enrich_canonical_list(
        canonical_list,
        akt_by_doc,
        case_id,
        all_matrikler=all_matrikler,
        doc_filename_by_id=doc_filename_by_id,
        progress_callback=progress_callback,
    )


def extract_canonical_from_attest(
    case_id: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[Servitut]:
    """Kører kun Pas 1: udtræk canonical liste fra tinglysningsattest."""
    chunks = storage_service.load_all_chunks(case_id)
    documents_by_id = _load_documents_by_id(
        case_id,
        list(dict.fromkeys(c.document_id for c in chunks)),
    )
    attest_chunks: list[Chunk] = []
    for c in chunks:
        doc = documents_by_id.get(c.document_id)
        if doc and doc.document_type == "tinglysningsattest":
            attest_chunks.append(c)
    if not attest_chunks:
        return []
    attest_by_doc: dict[str, list[Chunk]] = {}
    for c in attest_chunks:
        attest_by_doc.setdefault(c.document_id, []).append(c)
    return _extract_from_doc_chunks(
        attest_by_doc,
        case_id,
        "tinglysningsattest",
        progress_callback=progress_callback,
    )


def score_akt_chunks_for_case(
    case_id: str,
    canonical_list: List[Servitut],
) -> List[dict]:
    """
    Returnerer per-dok scoring-resultat til visning i Streamlit.
    Hvert element indeholder metadata om chunks og hvilke der er valgt som kandidater.
    """
    signals = build_scoring_signals(canonical_list)
    documents = {
        d.document_id: d
        for d in storage_service.list_documents(case_id)
        if d.document_type == "akt"
    }
    results = []
    for doc_id, doc in documents.items():
        chunks = storage_service.load_chunks(case_id, doc_id)
        if not chunks:
            continue
        scored = score_chunks(chunks, signals)
        candidates = select_candidate_chunks(chunks, canonical_list)
        candidate_ids = {c.chunk_id for c in candidates}
        max_score = max((s for s, _, _ in scored), default=0)
        chunk_details = [
            {
                "chunk_id": chunks[i].chunk_id,
                "page": chunks[i].page,
                "score": s,
                "reasons": r,
                "text_preview": chunks[i].text[:150],
                "selected": chunks[i].chunk_id in candidate_ids,
            }
            for s, i, r in scored
            if s > 0
        ]
        results.append(
            {
                "doc_id": doc_id,
                "filename": doc.filename,
                "total_chunks": len(chunks),
                "candidate_count": len(candidates),
                "candidate_chars": sum(len(c.text) for c in candidates),
                "max_score": max_score,
                "skipped": len(candidates) == 0,
                "chunk_details": chunk_details,
            }
        )
    return results
