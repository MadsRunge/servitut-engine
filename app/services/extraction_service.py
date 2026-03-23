from typing import List, Optional

from sqlmodel import Session

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
    extract_canonical_from_attest_segments,
    enrich_canonical_list,
)
from app.services import matrikel_service, storage_service
from app.services.extraction.enricher import (
    analyze_candidate_selection,
    build_scoring_signals,
    describe_scoring_inputs,
    get_chunk_scoring_rules,
    score_chunks,
    select_candidate_chunks,
)

logger = get_logger(__name__)


def _load_documents_by_id(
    session: Session, case_id: str, doc_ids: list[str]
) -> dict[str, Document]:
    requested = set(doc_ids)
    if not requested:
        return {}
    return {
        doc.document_id: doc
        for doc in storage_service.list_documents(session, case_id)
        if doc.document_id in requested
    }


def extract_servitutter(
    session: Session,
    chunks: List[Chunk],
    case_id: str,
    progress_callback: Optional[ProgressCallback] = None,
    cached_canonical: Optional[List[Servitut]] = None,
    observability_run_id: Optional[str] = None,
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
    documents_by_id = _load_documents_by_id(session, case_id, doc_ids)
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
        canonical_list = extract_canonical_from_attest_segments(
            session,
            attest_by_doc,
            case_id,
            progress_callback=progress_callback,
        )
        if session is not None:
            storage_service.save_canonical_list(session, case_id, canonical_list)
    logger.info(f"Canonical liste: {len(canonical_list)} servitutter")

    case = matrikel_service.sync_case_matrikler(session, case_id, attest_by_doc.keys())
    all_matrikler = [matrikel.parcel_number for matrikel in case.parcels] if case else []

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
        observability_run_id=observability_run_id,
    )


def extract_canonical_from_attest(
    session: Session,
    case_id: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[Servitut]:
    """Kører kun Pas 1: udtræk canonical liste fra tinglysningsattest."""
    chunks = storage_service.load_all_chunks(session, case_id)
    documents_by_id = _load_documents_by_id(
        session,
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
    return extract_canonical_from_attest_segments(
        session,
        attest_by_doc,
        case_id,
        progress_callback=progress_callback,
    )


def score_akt_chunks_for_case(
    session: Session,
    case_id: str,
    canonical_list: List[Servitut],
) -> List[dict]:
    """
    Returnerer per-dok scoring-resultat til visning i Streamlit.
    Hvert element indeholder metadata om chunks og hvilke der er valgt som kandidater.
    """
    signals = build_scoring_signals(canonical_list)
    scoring_inputs = describe_scoring_inputs(canonical_list)
    signal_lookup = scoring_inputs["signal_lookup"]
    rules = get_chunk_scoring_rules()
    documents = {
        d.document_id: d
        for d in storage_service.list_documents(session, case_id)
        if d.document_type == "akt"
    }
    results = []
    for doc_id, doc in documents.items():
        chunks = storage_service.load_chunks(session, case_id, doc_id)
        if not chunks:
            continue
        scored = score_chunks(chunks, signals)
        analysis = analyze_candidate_selection(chunks, canonical_list)
        candidates = select_candidate_chunks(chunks, canonical_list)
        candidate_ids = {c.chunk_id for c in candidates}
        selected_indices = set(analysis["selected_indices"])
        hit_indices = analysis["hit_indices"]
        candidate_cap_excluded = set(analysis["candidate_cap_excluded_indices"])
        char_cap_excluded = set(analysis["char_cap_excluded_indices"])
        score_by_idx = analysis["score_by_idx"]
        reasons_by_idx = analysis["reasons_by_idx"]
        max_score = max((s for s, _, _ in scored), default=0)
        visible_indices = sorted(
            {
                i for s, i, _ in scored if s > 0
            }
            | selected_indices
            | candidate_cap_excluded
            | char_cap_excluded
        )
        chunk_details = []
        for idx in visible_indices:
            chunk = chunks[idx]
            score = score_by_idx.get(idx, 0)
            reason_keys = reasons_by_idx.get(idx, [])
            matched_signals = [_expand_signal_reason(reason, signal_lookup) for reason in reason_keys]
            selection_state = _chunk_selection_state(
                idx,
                score,
                selected_indices,
                hit_indices,
                candidate_cap_excluded,
                char_cap_excluded,
            )
            chunk_details.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "page": chunk.page,
                    "score": score,
                    "reasons": reason_keys,
                    "matched_signals": matched_signals,
                    "selection_state": selection_state,
                    "selection_label": _chunk_selection_label(selection_state),
                    "selection_reason": _chunk_selection_reason(
                        selection_state,
                        idx,
                        analysis["context_sources"],
                        chunks,
                    ),
                    "text_preview": chunk.text[:240],
                    "text_length": len(chunk.text),
                    "selected": chunk.chunk_id in candidate_ids,
                    "rank": analysis["rank_by_idx"].get(idx),
                }
            )
        results.append(
            {
                "doc_id": doc_id,
                "filename": doc.filename,
                "total_chunks": len(chunks),
                "candidate_count": len(candidates),
                "candidate_chars": sum(len(c.text) for c in candidates),
                "max_score": max_score,
                "skipped": len(candidates) == 0,
                "rules": rules,
                "selection_summary": {
                    "hit_chunks": len(hit_indices),
                    "selected_hit_chunks": sum(1 for idx in selected_indices if idx in hit_indices),
                    "selected_context_chunks": sum(1 for idx in selected_indices if idx not in hit_indices),
                    "below_threshold_chunks": sum(
                        1
                        for score, idx, _ in scored
                        if 0 < score < rules["minimum_score"] and idx not in selected_indices
                    ),
                    "candidate_cap_excluded_chunks": len(candidate_cap_excluded),
                    "char_cap_excluded_chunks": len(char_cap_excluded),
                    "visible_chunk_details": len(chunk_details),
                },
                "chunk_details": chunk_details,
            }
        )
    return results


def describe_chunk_scoring_inputs(canonical_list: List[Servitut]) -> dict:
    scoring_inputs = describe_scoring_inputs(canonical_list)
    scoring_inputs.pop("signal_lookup", None)
    return scoring_inputs


def _expand_signal_reason(reason: str, signal_lookup: dict[str, dict]) -> dict:
    signal = signal_lookup.get(reason)
    if not signal:
        signal_type, _, normalized = reason.partition(":")
        return {
            "signal_key": reason,
            "signal_type": signal_type,
            "label": signal_type,
            "weight": 0,
            "description": "",
            "normalized_value": normalized,
            "display_values": [normalized] if normalized else [],
            "canonical_refs": [],
        }
    return {
        "signal_key": signal["signal_key"],
        "signal_type": signal["signal_type"],
        "label": signal["label"],
        "weight": signal["weight"],
        "description": signal["description"],
        "normalized_value": signal["normalized_value"],
        "display_values": list(signal["display_values"]),
        "canonical_refs": list(signal["canonical_refs"]),
    }


def _chunk_selection_state(
    idx: int,
    score: int,
    selected_indices: set[int],
    hit_indices: set[int],
    candidate_cap_excluded: set[int],
    char_cap_excluded: set[int],
) -> str:
    if idx in selected_indices and idx in hit_indices:
        return "selected_hit"
    if idx in selected_indices:
        return "selected_context"
    if idx in char_cap_excluded:
        return "excluded_char_cap"
    if idx in candidate_cap_excluded:
        return "excluded_candidate_cap"
    if score > 0:
        return "below_threshold"
    return "hidden"


def _chunk_selection_label(selection_state: str) -> str:
    return {
        "selected_hit": "Valgt til LLM som hit",
        "selected_context": "Valgt til LLM som kontekst",
        "excluded_char_cap": "Fravalgt pga. tegnloft",
        "excluded_candidate_cap": "Fravalgt pga. top-12 cap",
        "below_threshold": "Match fundet, men under tærskel",
        "hidden": "Skjult",
    }.get(selection_state, selection_state)


def _chunk_selection_reason(
    selection_state: str,
    idx: int,
    context_sources: dict[int, list[int]],
    chunks: list[Chunk],
) -> str:
    if selection_state == "selected_hit":
        return "Chunken nåede minimumscore og er sendt til LLM."
    if selection_state == "selected_context":
        neighbors = [
            f"side {chunks[hit_idx].page}"
            for hit_idx in context_sources.get(idx, [])
            if hit_idx != idx
        ]
        if neighbors:
            return f"Chunken er med som nabokontekst til hit på {', '.join(neighbors)}."
        return "Chunken er med som kontekst til et nærliggende hit."
    if selection_state == "excluded_char_cap":
        return "Chunken var blandt de prioriterede kandidater, men røg ud ved tegnloftet."
    if selection_state == "excluded_candidate_cap":
        return "Chunken var i kontekstvinduet, men røg ud ved top-12 cap."
    if selection_state == "below_threshold":
        return "Chunken havde signal, men ikke nok til at blive sendt videre."
    return ""
