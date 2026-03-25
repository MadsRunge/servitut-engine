import json
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from queue import Queue
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.servitut import Evidence, Servitut
from app.services import pipeline_observability
from app.services.extraction.llm_extractor import _build_chunks_text, _parse_llm_response
from app.services.extraction.matching import _extract_date_components, _servitut_matches
from app.services.extraction.merger import _enrich_canonical
from app.services.extraction.normalization import (
    coerce_optional_str,
    coerce_str_list,
    parse_registered_at,
)
from app.services.extraction.progress import ProgressCallback, _drain_progress_queue, _emit_progress
from app.services.extraction.prompts import _load_prompt
from app.services.llm_service import generate_text
from app.utils.ids import generate_servitut_id

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Chunk scoring constants
# ---------------------------------------------------------------------------

_SCORE_AKT_NR         = 10   # eksakt archive_number-match (normaliseret)
_SCORE_DATE_REF       = 5    # date_reference-match (normaliseret)
_SCORE_LOB_SUFFIX     = 3    # løbenummer-suffix match
_SCORE_MATRIKEL       = 2    # matrikelreference
_SCORE_TITLE_WORD     = 1    # ord ≥6 tegn fra canonical title
_MIN_SCORE_INCLUDE    = 2    # minimum for at en chunk er kandidat
_MAX_CANDIDATE_CHUNKS = 12
_MAX_CANDIDATE_CHARS  = 16_000

_TITLE_STOPWORDS = {
    "vedrørende", "tinglyst", "matrikel", "matriklerne",
    "ejendommen", "ejere", "servitut", "servitutter",
    # Juridiske standardvendinger der optræder bredt i pantebrevs-tekst:
    "prioritet", "pantegæld", "forud",
}

_SCORING_RULE_META = {
    "archive_number": {
        "label": "Akt nr.",
        "weight": _SCORE_AKT_NR,
        "description": "Eksakt match på normaliseret aktnummer",
    },
    "date_ref": {
        "label": "Løbenummer / dato",
        "weight": _SCORE_DATE_REF,
        "description": "Match på hele tinglysningsdatoen med løbenummer",
    },
    "lob_suffix": {
        "label": "Løbenummer-suffix",
        "weight": _SCORE_LOB_SUFFIX,
        "description": "Match på løbenummer-suffix fra date_reference",
    },
    "matrikel": {
        "label": "Matrikel",
        "weight": _SCORE_MATRIKEL,
        "description": "Match på matrikelhenvisning fra attestens scope",
    },
    "title_word": {
        "label": "Titelord",
        "weight": _SCORE_TITLE_WORD,
        "description": "Match på lange nøgleord fra canonical-titlen",
    },
}


def _resolve_extraction_provider() -> str | None:
    if settings.EXTRACTION_LLM_PROVIDER.strip():
        return settings.EXTRACTION_LLM_PROVIDER.strip()
    return None


def _resolve_extraction_model() -> str | None:
    if settings.EXTRACTION_MODEL.strip():
        return settings.EXTRACTION_MODEL.strip()
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_akt_nr(archive_number: str) -> str:
    """Strip spaces, hyphens and lowercase — used for fuzzy archive_number comparison."""
    return re.sub(r"[\s\-]", "", archive_number).lower()


def get_chunk_scoring_rules(context_window: int = 1) -> dict:
    return {
        "signal_weights": [
            {
                "signal_type": signal_type,
                "label": meta["label"],
                "weight": meta["weight"],
                "description": meta["description"],
            }
            for signal_type, meta in _SCORING_RULE_META.items()
        ],
        "minimum_score": _MIN_SCORE_INCLUDE,
        "context_window": context_window,
        "max_candidate_chunks": _MAX_CANDIDATE_CHUNKS,
        "max_candidate_chars": _MAX_CANDIDATE_CHARS,
    }


def _canonical_ref_summary(servitut: Servitut) -> dict:
    return {
        "date_reference": servitut.date_reference or "—",
        "title": servitut.title or "—",
        "archive_number": servitut.archive_number or "—",
        "applies_to_parcel_numbers": list(servitut.applies_to_parcel_numbers or []),
        "raw_parcel_references": list(servitut.raw_parcel_references or []),
        "raw_scope_text": servitut.raw_scope_text or "—",
    }


def _add_signal_catalog_entry(
    catalog: dict[str, dict],
    signal_type: str,
    normalized_value: str,
    display_value: str,
    servitut: Servitut,
) -> None:
    if not normalized_value:
        return

    key = f"{signal_type}:{normalized_value}"
    meta = _SCORING_RULE_META[signal_type]
    entry = catalog.setdefault(
        key,
        {
            "signal_key": key,
            "signal_type": signal_type,
            "label": meta["label"],
            "weight": meta["weight"],
            "description": meta["description"],
            "normalized_value": normalized_value,
            "display_values": [],
            "canonical_refs": [],
        },
    )
    if display_value and display_value not in entry["display_values"]:
        entry["display_values"].append(display_value)
    ref_summary = _canonical_ref_summary(servitut)
    if ref_summary not in entry["canonical_refs"]:
        entry["canonical_refs"].append(ref_summary)


def build_scoring_signal_catalog(canonical_list: List[Servitut]) -> dict[str, dict]:
    catalog: dict[str, dict] = {}
    for servitut in canonical_list:
        if servitut.archive_number:
            normalized = _normalize_akt_nr(servitut.archive_number)
            _add_signal_catalog_entry(catalog, "archive_number", normalized, servitut.archive_number, servitut)

        if servitut.date_reference:
            normalized_date = re.sub(r"[\s.\-]", "", servitut.date_reference).lower()
            _add_signal_catalog_entry(
                catalog,
                "date_ref",
                normalized_date,
                servitut.date_reference,
                servitut,
            )
            comps = _extract_date_components(servitut.date_reference)
            lob = comps.get("løbenummer_suffix")
            if lob:
                normalized_lob = re.sub(r"[\s.\-]", "", lob).lower()
                _add_signal_catalog_entry(catalog, "lob_suffix", normalized_lob, lob, servitut)

        for matrikel in (servitut.applies_to_parcel_numbers or []):
            if matrikel:
                _add_signal_catalog_entry(
                    catalog,
                    "matrikel",
                    matrikel.lower(),
                    matrikel.lower(),
                    servitut,
                )

        if servitut.title:
            for word in servitut.title.lower().split():
                word_clean = re.sub(r"[^\w]", "", word)
                if len(word_clean) >= 6 and word_clean not in _TITLE_STOPWORDS:
                    _add_signal_catalog_entry(
                        catalog,
                        "title_word",
                        word_clean,
                        word_clean,
                        servitut,
                    )
    return catalog


def describe_scoring_inputs(canonical_list: List[Servitut]) -> dict:
    catalog = build_scoring_signal_catalog(canonical_list)
    signal_groups = []
    for signal_type, meta in _SCORING_RULE_META.items():
        entries = sorted(
            (entry for entry in catalog.values() if entry["signal_type"] == signal_type),
            key=lambda entry: (entry["normalized_value"], entry["display_values"]),
        )
        signal_groups.append(
            {
                "signal_type": signal_type,
                "label": meta["label"],
                "weight": meta["weight"],
                "description": meta["description"],
                "count": len(entries),
                "signals": entries,
            }
        )

    canonical_rows = []
    for servitut in canonical_list:
        derived_signals = []
        for entry in catalog.values():
            if _canonical_ref_summary(servitut) in entry["canonical_refs"]:
                derived_signals.append(
                    {
                        "signal_type": entry["signal_type"],
                        "label": entry["label"],
                        "weight": entry["weight"],
                        "values": entry["display_values"],
                    }
                )
        canonical_rows.append(
            {
                "date_reference": servitut.date_reference or "—",
                "title": servitut.title or "—",
                "archive_number": servitut.archive_number or "—",
                "applies_to_parcel_numbers": list(servitut.applies_to_parcel_numbers or []),
                "raw_parcel_references": list(servitut.raw_parcel_references or []),
                "raw_scope_text": servitut.raw_scope_text or "—",
                "derived_signals": derived_signals,
            }
        )

    return {
        "rules": get_chunk_scoring_rules(),
        "signal_groups": signal_groups,
        "canonical_rows": canonical_rows,
        "signal_lookup": catalog,
    }


def _find_relevant_chunks(
    chunk_list: List[Chunk],
    date_ref: Optional[str],
    archive_number: Optional[str],
) -> List[Chunk]:
    """
    Return chunks that mention this servitut's date_reference or archive_number.
    Falls back to the first three chunks if no keyword match is found.
    """
    needles: list[str] = []
    if date_ref:
        # Normalised: strip internal spaces/hyphens for loose substring matching
        needles.append(re.sub(r"[\s\-]", "", date_ref).lower())
    if archive_number:
        needles.append(_normalize_akt_nr(archive_number))

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
    archive_number: Optional[str] = None,
) -> List[Evidence]:
    relevant = _find_relevant_chunks(chunk_list, date_ref, archive_number)
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
            "archive_number": s.archive_number,
            "title": s.title,
        }
        for s in canonical_list
    ]
    return json.dumps(items, ensure_ascii=False, indent=2)

def _resolve_canonical_key(
    item: dict,
    canonical_by_date: dict[str, str],
    canonical_by_akt: dict[str, list[str]],
    canonical_list: Optional[List[Servitut]] = None,
    canonical_years: Optional[dict[str, int]] = None,
) -> Optional[tuple[str, int]]:
    """
    Map an LLM-returned enrichment item back to a canonical date_reference key.

    Returns (canonical_key, priority) where priority indicates match strength:
      1 = Normalised archive_number match (direct — strongest)
      2 = Exact date_reference match
      3 = Fuzzy date matching (løbenummer suffix → full date → unikt år)
    Returns None if no canonical is found.
    """
    item_akt = item.get("archive_number")
    item_date = item.get("date_reference") or ""
    if item_akt:
        key = _normalize_akt_nr(item_akt)
        candidates = canonical_by_akt.get(key, [])
        if len(candidates) == 1:
            # Unambiguous archive_number match
            return (candidates[0], 1)
        elif len(candidates) > 1:
            # Ambiguous archive_number (same arkivskab, multiple servitutter) —
            # disambiguate via date_reference if LLM provided one
            if item_date:
                exact = canonical_by_date.get(item_date)
                if exact and exact in candidates:
                    return (exact, 1)
                # Fuzzy: find which candidate year matches item_date
                if canonical_list:
                    pseudo = Servitut(easement_id="__tmp__", case_id="", source_document="", date_reference=item_date)
                    for canonical in canonical_list:
                        if (canonical.date_reference or "") in candidates and _servitut_matches(canonical, pseudo, canonical_years):
                            return (canonical.date_reference or "", 1)
            # Cannot disambiguate — fall through to date-based matching below
            logger.debug(f"Ambigt archive_number {item_akt!r} → {candidates} — falder tilbage til dato-match")

    exact = canonical_by_date.get(item_date)
    if exact:
        return (exact, 2)

    # Priority 3: fuzzy date matching
    if item_date and canonical_list:
        pseudo = Servitut(easement_id="__tmp__", case_id="", source_document="", date_reference=item_date)
        for canonical in canonical_list:
            if _servitut_matches(canonical, pseudo, canonical_years):
                return (canonical.date_reference or "", 3)

    return None


# ---------------------------------------------------------------------------
# Deterministisk chunk-selektion
# ---------------------------------------------------------------------------

def build_scoring_signals(canonical_list: List[Servitut]) -> dict[str, set[str]]:
    """Preberegn normaliserede søgesignaler fra canonical-listen."""
    signals: dict[str, set[str]] = {
        "archive_number": set(),
        "date_ref": set(),
        "lob_suffix": set(),
        "matrikel": set(),
        "title_word": set(),
    }
    for entry in build_scoring_signal_catalog(canonical_list).values():
        signals[entry["signal_type"]].add(entry["normalized_value"])
    return signals


def analyze_candidate_selection(
    chunk_list: List[Chunk],
    canonical_list: List[Servitut],
    context_window: int = 1,
) -> dict:
    signals = build_scoring_signals(canonical_list)
    scored = score_chunks(chunk_list, signals)
    max_score = max((score for score, _, _ in scored), default=0)

    if max_score == 0:
        return {
            "signals": signals,
            "scored": scored,
            "max_score": 0,
            "hit_indices": set(),
            "context_indices": set(),
            "selected_indices": [],
            "candidate_cap_excluded_indices": [],
            "char_cap_excluded_indices": [],
            "score_by_idx": {i: score for score, i, _ in scored},
            "reasons_by_idx": {i: reasons for score, i, reasons in scored},
            "rank_by_idx": {},
            "context_sources": {},
            "selected_char_count": 0,
        }

    score_by_idx = {i: score for score, i, _ in scored}
    reasons_by_idx = {i: reasons for score, i, reasons in scored}
    hit_indices = {i for score, i, _ in scored if score >= _MIN_SCORE_INCLUDE}

    context_indices: set[int] = set()
    context_sources: dict[int, list[int]] = {}
    for hit_idx in hit_indices:
        for idx in range(max(0, hit_idx - context_window), min(len(chunk_list), hit_idx + context_window + 1)):
            context_indices.add(idx)
            context_sources.setdefault(idx, [])
            if hit_idx not in context_sources[idx]:
                context_sources[idx].append(hit_idx)

    sorted_by_score = sorted(context_indices, key=lambda idx: score_by_idx.get(idx, 0), reverse=True)
    rank_by_idx = {idx: rank + 1 for rank, idx in enumerate(sorted_by_score)}
    candidate_cap_excluded = sorted(sorted_by_score[_MAX_CANDIDATE_CHUNKS:])
    top_indices = sorted(sorted_by_score[:_MAX_CANDIDATE_CHUNKS])

    selected_indices: list[int] = []
    char_cap_excluded: list[int] = []
    total_chars = 0
    for idx in top_indices:
        chunk = chunk_list[idx]
        if total_chars + len(chunk.text) > _MAX_CANDIDATE_CHARS:
            char_cap_excluded = top_indices[top_indices.index(idx):]
            break
        selected_indices.append(idx)
        total_chars += len(chunk.text)

    return {
        "signals": signals,
        "scored": scored,
        "max_score": max_score,
        "hit_indices": hit_indices,
        "context_indices": context_indices,
        "selected_indices": selected_indices,
        "candidate_cap_excluded_indices": candidate_cap_excluded,
        "char_cap_excluded_indices": char_cap_excluded,
        "score_by_idx": score_by_idx,
        "reasons_by_idx": reasons_by_idx,
        "rank_by_idx": rank_by_idx,
        "context_sources": context_sources,
        "selected_char_count": total_chars,
    }


def score_chunks(
    chunk_list: List[Chunk],
    signals: dict[str, set[str]],
) -> list[tuple[int, int, list[str]]]:
    """Score chunks mod canonical-signaler. Returnerer (score, index, reasons) for hvert chunk."""
    scored: list[tuple[int, int, list[str]]] = []
    for i, chunk in enumerate(chunk_list):
        text_norm = re.sub(r"[\s.\-]", "", chunk.text).lower()
        text_lower = chunk.text.lower()
        score = 0
        reasons: list[str] = []

        for sig in signals["archive_number"]:
            if sig and sig in text_norm:
                score += _SCORE_AKT_NR
                reasons.append(f"archive_number:{sig}")
        for sig in signals["date_ref"]:
            if sig and sig in text_norm:
                score += _SCORE_DATE_REF
                reasons.append(f"date_ref:{sig}")
        for sig in signals["lob_suffix"]:
            if sig and sig in text_norm:
                score += _SCORE_LOB_SUFFIX
                reasons.append(f"lob_suffix:{sig}")
        for sig in signals["matrikel"]:
            if sig and sig in text_lower:
                score += _SCORE_MATRIKEL
                reasons.append(f"matrikel:{sig}")
        for sig in signals["title_word"]:
            if sig and sig in text_lower:
                score += _SCORE_TITLE_WORD
                reasons.append(f"title_word:{sig}")

        scored.append((score, i, reasons))
    return scored


def select_candidate_chunks(
    chunk_list: List[Chunk],
    canonical_list: List[Servitut],
    context_window: int = 1,
) -> List[Chunk]:
    """
    Score chunks mod canonical-signaler og returner top-N kandidater med kontekstvinduer.
    Returnerer tom liste hvis ingen chunks har tilstrækkelig signal (→ skip LLM-kald).
    """
    analysis = analyze_candidate_selection(chunk_list, canonical_list, context_window=context_window)
    max_score = analysis["max_score"]
    if max_score == 0:
        logger.info("select_candidate_chunks: ingen signal — springer LLM over")
        return []
    result_chunks = [chunk_list[idx] for idx in analysis["selected_indices"]]
    total_chars = analysis["selected_char_count"]

    logger.info(
        f"select_candidate_chunks: {len(result_chunks)}/{len(chunk_list)} chunks valgt, "
        f"{total_chars} tegn, max_score={max_score}"
    )
    for s, i, reasons in analysis["scored"]:
        if s > 0:
            logger.debug(f"  chunk[{i}] score={s} reasons={reasons}")

    return result_chunks


# Backwards-compatible aliases for existing imports/tests during migration.
_build_scoring_signals = build_scoring_signals
_score_chunks = score_chunks
_select_candidate_chunks = select_candidate_chunks


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _enrich_from_doc(
    doc_id: str,
    chunk_list: List[Chunk],
    canonical_list: List[Servitut],
    all_matrikler: List[str],
    progress_callback: Optional[ProgressCallback],
    progress_queue=None,
    doc_filename: Optional[str] = None,
) -> List[dict]:
    """One LLM call per akt: ask which canonical servitutter it contains.
    chunk_list should already be pre-filtered candidate chunks (Fase 1).
    """
    callback = progress_callback
    if progress_queue is not None:
        callback = lambda event: progress_queue.put(event)  # noqa: E731

    _emit_progress(
        callback,
        doc_id=doc_id,
        source_type="akt",
        stage="running",
        progress=0.2,
        message="Målrettet berigelse",
    )

    prompt_template = _load_prompt("enrich_servitut")
    canonical_json = _build_canonical_json(canonical_list)

    chunks_text = _build_chunks_text(chunk_list)
    akt_dok_hint = doc_filename or doc_id
    prompt = (
        prompt_template
        .replace("{canonical_json}", canonical_json)
        .replace("{all_matrikler_json}", json.dumps(all_matrikler, ensure_ascii=False))
        .replace("{akt_dok_hint}", akt_dok_hint)
        .replace("{chunks_text}", chunks_text)
    )

    try:
        _emit_progress(
            callback,
            doc_id=doc_id,
            source_type="akt",
            stage="requesting",
            progress=0.5,
            message="Sender LLM-kald",
        )
        response_text = generate_text(
            prompt,
            max_tokens=4096,
            provider=_resolve_extraction_provider(),
            default_model=_resolve_extraction_model(),
        )
        items = _parse_llm_response(response_text)
        _emit_progress(
            callback,
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
            callback,
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
    doc_filename_by_id: Optional[dict[str, str]] = None,
    progress_callback: Optional[ProgressCallback] = None,
    observability_run_id: Optional[str] = None,
) -> List[Servitut]:
    """
    Canonical-driven enrichment.

    For each akt document, one LLM call returns the subset of canonical
    servitutter it describes.  Matching uses archive_number (normalised) first,
    then date_reference.  Evidence chunks are chosen by keyword proximity
    to the matched servitut, not positionally.
    """
    if not akt_chunks_by_doc or not canonical_list:
        return canonical_list

    all_matrikler = all_matrikler or []
    pipeline_started_at = time.perf_counter()

    # Build two lookup tables: date_reference → canonical_date_key
    #                          normalised_akt_nr → canonical_date_key
    canonical_by_date: dict[str, str] = {
        (s.date_reference or ""): (s.date_reference or "")
        for s in canonical_list
    }
    # Byg archive_number → liste af canonical keys (et archive_number kan referere til flere servitutter
    # der deler samme fysiske arkivskab, f.eks. 40_C_239 → 1903 + 1975)
    canonical_by_akt: dict[str, list[str]] = {}
    for s in canonical_list:
        if s.archive_number:
            key = _normalize_akt_nr(s.archive_number)
            canonical_by_akt.setdefault(key, []).append(s.date_reference or "")
    # Year-frequency table for fuzzy matching (unambiguous year → 1 match)
    canonical_years: dict[str, int] = {}
    for s in canonical_list:
        y = _extract_date_components(s.date_reference).get("year")
        if y:
            canonical_years[y] = canonical_years.get(y, 0) + 1
    # key (canonical date_reference) → (best item dict, doc_id, chunk_list, priority)
    # priority 1=archive_number match, 2=exact date, 3=fuzzy date — lower = better
    best_by_key: dict[str, tuple[dict, str, List[Chunk], int]] = {}
    # orphan_key → (item, doc_id, chunk_list) — fundet i akt men ikke i attest.
    # Disse materialiseres ikke som selvstændige servitutter; de tælles kun til observability.
    orphan_best: dict[str, tuple[dict, str, List[Chunk]]] = {}

    # --- Fase 1: Deterministisk chunk-filtrering ---
    logger.info("Fase 1: Scorer og filtrerer akt-chunks mod canonical-signaler")
    candidate_chunks_by_doc: dict[str, list[Chunk]] = {}
    candidate_metrics_by_doc: dict[str, dict] = {}
    phase1_started_at = time.perf_counter()
    for doc_id, chunk_list in akt_chunks_by_doc.items():
        analysis = analyze_candidate_selection(chunk_list, canonical_list)
        candidates = [chunk_list[idx] for idx in analysis["selected_indices"]]
        candidate_metrics_by_doc[doc_id] = {
            "total_chunks": len(chunk_list),
            "candidate_chunks": len(candidates),
            "candidate_chars": analysis["selected_char_count"],
            "max_score": analysis["max_score"],
            "hit_count": len(analysis["hit_indices"]),
            "selected_indices": list(analysis["selected_indices"]),
            "skipped": len(candidates) == 0,
        }
        if candidates:
            candidate_chunks_by_doc[doc_id] = candidates
        else:
            logger.info(f"  {doc_id}: ingen kandidat-chunks — springer LLM-kald over")
            _emit_progress(
                progress_callback,
                doc_id=doc_id,
                source_type="akt",
                stage="skipped",
                progress=1.0,
                message="Ingen relevante chunks — sprunget over",
                servitut_count=0,
            )
    logger.info(
        f"Fase 1 færdig: {len(candidate_chunks_by_doc)}/{len(akt_chunks_by_doc)} docs → LLM"
    )
    phase1_duration = round(time.perf_counter() - phase1_started_at, 3)

    # --- Fase 2: LLM enrichment (kun docs med kandidater) ---
    max_workers = min(max(1, settings.EXTRACTION_MAX_CONCURRENCY), len(candidate_chunks_by_doc))
    ordered_doc_ids = list(candidate_chunks_by_doc.keys())
    phase2_started_at = time.perf_counter()

    for doc_id in ordered_doc_ids:
        _emit_progress(
            progress_callback,
            doc_id=doc_id,
            source_type="akt",
            stage="queued",
            progress=0.0,
            message="Sat i kø",
        )

    progress_queue: Optional[Queue] = Queue() if progress_callback else None

    if max_workers <= 1:
        items_by_doc: dict[str, list] = {}
        for doc_id in ordered_doc_ids:
            items_by_doc[doc_id] = _enrich_from_doc(
                doc_id,
                candidate_chunks_by_doc[doc_id],
                canonical_list,
                all_matrikler,
                progress_callback,
                progress_queue=None,
                doc_filename=doc_filename_by_id.get(doc_id) if doc_filename_by_id else None,
            )
    else:
        logger.info(
            f"Fase 2: Parallel enrichment — {len(ordered_doc_ids)} docs, max_workers={max_workers}"
        )
        items_by_doc = {}
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="enrich-doc") as executor:
            futures = {
                executor.submit(
                    _enrich_from_doc,
                    doc_id,
                    candidate_chunks_by_doc[doc_id],
                    canonical_list,
                    all_matrikler,
                    None,
                    progress_queue,
                    doc_filename_by_id.get(doc_id) if doc_filename_by_id else None,
                ): doc_id
                for doc_id in ordered_doc_ids
            }
            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                _drain_progress_queue(progress_queue, progress_callback)
                for future in done:
                    doc_id = futures[future]
                    try:
                        items_by_doc[doc_id] = future.result()
                    except Exception as exc:
                        logger.error(f"Enrichment worker failed for doc {doc_id}: {exc}")
                        items_by_doc[doc_id] = []
            _drain_progress_queue(progress_queue, progress_callback)
    phase2_duration = round(time.perf_counter() - phase2_started_at, 3)

    # --- Merge results serially ---
    for doc_id in ordered_doc_ids:
        items = items_by_doc.get(doc_id, [])
        doc_chunks = candidate_chunks_by_doc[doc_id]
        for item in items:
            result_key = _resolve_canonical_key(item, canonical_by_date, canonical_by_akt, canonical_list, canonical_years)
            if result_key is None:
                # Ikke i tinglysningsattest — behold kun til observability/debug.
                orphan_key = _normalize_akt_nr(item.get("archive_number") or "") or (item.get("date_reference") or "")
                if orphan_key and orphan_key not in orphan_best:
                    orphan_best[orphan_key] = (item, doc_id, doc_chunks)
                elif orphan_key:
                    existing_conf = float(orphan_best[orphan_key][0].get("confidence", 0))
                    if float(item.get("confidence", 0.5) or 0.5) > existing_conf:
                        orphan_best[orphan_key] = (item, doc_id, doc_chunks)
                logger.debug(
                    f"Umatched enrichment item (not in attest): "
                    f"date={item.get('date_reference')!r}, archive_number={item.get('archive_number')!r}"
                )
                continue
            key, priority = result_key
            item_conf = float(item.get("confidence", 0.5) or 0.5)
            existing = best_by_key.get(key)
            if existing is None:
                best_by_key[key] = (item, doc_id, doc_chunks, priority)
            else:
                existing_conf = float(existing[0].get("confidence", 0))
                existing_priority = existing[3]
                # Lower priority number = better match; confidence breaks ties
                if priority < existing_priority or (priority == existing_priority and item_conf > existing_conf):
                    best_by_key[key] = (item, doc_id, doc_chunks, priority)

    # Apply enrichments
    result: List[Servitut] = []
    matched = 0
    for canonical in canonical_list:
        key = canonical.date_reference or ""
        entry = best_by_key.get(key)
        if entry:
            item, doc_id, chunk_list, _priority = entry
            enriched_date = coerce_optional_str(item.get("date_reference")) or canonical.date_reference
            enriched_akt_nr = coerce_optional_str(item.get("archive_number")) or canonical.archive_number
            applies_to_parcel_numbers = coerce_str_list(item.get("applies_to_parcel_numbers"))
            akt_srv = Servitut(
                easement_id=generate_servitut_id(),
                case_id=case_id,
                source_document=doc_id,
                date_reference=enriched_date,
                registered_at=parse_registered_at(item.get("registered_at"), enriched_date),
                archive_number=enriched_akt_nr,
                title=coerce_optional_str(item.get("title")) or canonical.title,
                summary=coerce_optional_str(item.get("summary")),
                beneficiary=coerce_optional_str(item.get("beneficiary")),
                disposition_type=coerce_optional_str(item.get("disposition_type")),
                legal_type=coerce_optional_str(item.get("legal_type")),
                construction_relevance=bool(item.get("construction_relevance", False)),
                construction_impact=coerce_optional_str(item.get("construction_impact")),
                action_note=coerce_optional_str(item.get("action_note")),
                applies_to_parcel_numbers=applies_to_parcel_numbers,
                raw_parcel_references=coerce_str_list(item.get("raw_parcel_references"))
                or applies_to_parcel_numbers,
                raw_scope_text=coerce_optional_str(item.get("raw_scope_text"))
                or coerce_optional_str(item.get("scope_basis")),
                scope_source=coerce_optional_str(item.get("scope_source")) or "akt",
                scope_basis=coerce_optional_str(item.get("scope_basis")),
                scope_confidence=item.get("scope_confidence"),
                confidence=float(item.get("confidence", 0.5) or 0.5),
                evidence=_make_akt_evidence(chunk_list, enriched_date, enriched_akt_nr),
            )
            result.append(_enrich_canonical(canonical, akt_srv))
            matched += 1
        else:
            result.append(canonical)

    dropped_unconfirmed_count = len(orphan_best)
    if dropped_unconfirmed_count:
        logger.info(
            "Droppede %d akt-fund, som ikke kunne matches til tinglysningsattesten",
            dropped_unconfirmed_count,
        )

    logger.info(
        f"Enrichment færdig: {matched}/{len(canonical_list)} beriget, "
        f"{dropped_unconfirmed_count} akt-fund droppet (ikke i attest)"
    )
    total_duration = round(time.perf_counter() - pipeline_started_at, 3)
    observability_payload = {
        "pipeline": "extraction_enrichment",
        "case_id": case_id,
        "canonical_count": len(canonical_list),
        "total_documents": len(akt_chunks_by_doc),
        "candidate_documents": len(candidate_chunks_by_doc),
        "skipped_documents": len(akt_chunks_by_doc) - len(candidate_chunks_by_doc),
        "candidate_chunks_total": sum(metrics["candidate_chunks"] for metrics in candidate_metrics_by_doc.values()),
        "candidate_chars_total": sum(metrics["candidate_chars"] for metrics in candidate_metrics_by_doc.values()),
        "phase1_duration_seconds": phase1_duration,
        "phase2_duration_seconds": phase2_duration,
        "total_duration_seconds": total_duration,
        "max_workers": max_workers,
        "matched_servitutter": matched,
        "unconfirmed_servitutter": 0,
        "dropped_unconfirmed_servitutter": dropped_unconfirmed_count,
        "documents": [
            {
                "doc_id": doc_id,
                "filename": doc_filename_by_id.get(doc_id) if doc_filename_by_id else None,
                **candidate_metrics_by_doc[doc_id],
                "llm_items": len(items_by_doc.get(doc_id, [])),
            }
            for doc_id in akt_chunks_by_doc
        ],
    }
    observability_path = pipeline_observability.write_extraction_run_summary(
        case_id,
        observability_payload,
        run_id=observability_run_id,
    )
    logger.info(
        "Extraction observability: case=%s canonical=%d candidate_docs=%d/%d candidate_chunks=%d total=%.3fs path=%s",
        case_id,
        len(canonical_list),
        len(candidate_chunks_by_doc),
        len(akt_chunks_by_doc),
        observability_payload["candidate_chunks_total"],
        total_duration,
        observability_path,
    )
    return result
