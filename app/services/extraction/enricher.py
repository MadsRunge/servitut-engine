import json
import re
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.servitut import Evidence, Servitut
from app.services.extraction.llm_extractor import _build_chunks_text, _parse_llm_response
from app.services.extraction.matching import _extract_date_components, _servitut_matches
from app.services.extraction.merger import _enrich_canonical
from app.services.extraction.normalization import (
    coerce_optional_str,
    coerce_str_list,
    parse_registered_at,
)
from app.services.extraction.progress import ProgressCallback, _emit_progress
from app.services.extraction.prompts import _load_prompt
from app.services.llm_service import generate_text
from app.utils.ids import generate_servitut_id

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Chunk scoring constants
# ---------------------------------------------------------------------------

_SCORE_AKT_NR         = 10   # eksakt akt_nr-match (normaliseret)
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
      1 = Normalised akt_nr match (direct — strongest)
      2 = Exact date_reference match
      3 = Fuzzy date matching (løbenummer suffix → full date → unikt år)
    Returns None if no canonical is found.
    """
    item_akt = item.get("akt_nr")
    item_date = item.get("date_reference") or ""
    if item_akt:
        key = _normalize_akt_nr(item_akt)
        candidates = canonical_by_akt.get(key, [])
        if len(candidates) == 1:
            # Unambiguous akt_nr match
            return (candidates[0], 1)
        elif len(candidates) > 1:
            # Ambiguous akt_nr (same arkivskab, multiple servitutter) —
            # disambiguate via date_reference if LLM provided one
            if item_date:
                exact = canonical_by_date.get(item_date)
                if exact and exact in candidates:
                    return (exact, 1)
                # Fuzzy: find which candidate year matches item_date
                if canonical_list:
                    pseudo = Servitut(servitut_id="__tmp__", case_id="", source_document="", date_reference=item_date)
                    for canonical in canonical_list:
                        if (canonical.date_reference or "") in candidates and _servitut_matches(canonical, pseudo, canonical_years):
                            return (canonical.date_reference or "", 1)
            # Cannot disambiguate — fall through to date-based matching below
            logger.debug(f"Ambigt akt_nr {item_akt!r} → {candidates} — falder tilbage til dato-match")

    exact = canonical_by_date.get(item_date)
    if exact:
        return (exact, 2)

    # Priority 3: fuzzy date matching
    if item_date and canonical_list:
        pseudo = Servitut(servitut_id="__tmp__", case_id="", source_document="", date_reference=item_date)
        for canonical in canonical_list:
            if _servitut_matches(canonical, pseudo, canonical_years):
                return (canonical.date_reference or "", 3)

    return None


# ---------------------------------------------------------------------------
# Deterministisk chunk-selektion
# ---------------------------------------------------------------------------

def _build_scoring_signals(canonical_list: List[Servitut]) -> dict[str, set[str]]:
    """Preberegn normaliserede søgesignaler fra canonical-listen."""
    signals: dict[str, set[str]] = {
        "akt_nr": set(),
        "date_ref": set(),
        "lob_suffix": set(),
        "matrikel": set(),
        "title_word": set(),
    }
    for s in canonical_list:
        if s.akt_nr:
            signals["akt_nr"].add(_normalize_akt_nr(s.akt_nr))
        if s.date_reference:
            signals["date_ref"].add(re.sub(r"[\s.\-]", "", s.date_reference).lower())
            comps = _extract_date_components(s.date_reference)
            lob = comps.get("løbenummer_suffix")
            if lob:
                signals["lob_suffix"].add(re.sub(r"[\s.\-]", "", lob).lower())
        for m in (s.applies_to_matrikler or []):
            if m:
                signals["matrikel"].add(m.lower())
        if s.title:
            for word in s.title.lower().split():
                word_clean = re.sub(r"[^\w]", "", word)
                if len(word_clean) >= 6 and word_clean not in _TITLE_STOPWORDS:
                    signals["title_word"].add(word_clean)
    return signals


def _score_chunks(
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

        for sig in signals["akt_nr"]:
            if sig and sig in text_norm:
                score += _SCORE_AKT_NR
                reasons.append(f"akt_nr:{sig}")
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


def _select_candidate_chunks(
    chunk_list: List[Chunk],
    canonical_list: List[Servitut],
    context_window: int = 1,
) -> List[Chunk]:
    """
    Score chunks mod canonical-signaler og returner top-N kandidater med kontekstvinduer.
    Returnerer tom liste hvis ingen chunks har tilstrækkelig signal (→ skip LLM-kald).
    """
    signals = _build_scoring_signals(canonical_list)
    scored = _score_chunks(chunk_list, signals)

    max_score = max((s for s, _, _ in scored), default=0)
    if max_score == 0:
        logger.info("_select_candidate_chunks: ingen signal — springer LLM over")
        return []

    score_by_idx = {i: s for s, i, _ in scored}
    hit_indices = {i for s, i, _ in scored if s >= _MIN_SCORE_INCLUDE}

    with_context: set[int] = set()
    for i in hit_indices:
        for j in range(max(0, i - context_window), min(len(chunk_list), i + context_window + 1)):
            with_context.add(j)

    # Cap: sorter efter score desc, tag top 12, sorter tilbage til dokumentrækkefølge
    sorted_by_score = sorted(with_context, key=lambda i: score_by_idx.get(i, 0), reverse=True)
    top_indices = sorted(sorted_by_score[:_MAX_CANDIDATE_CHUNKS])

    # Anvend tegnloft i dokumentrækkefølge
    result_chunks: list[Chunk] = []
    total_chars = 0
    for i in top_indices:
        chunk = chunk_list[i]
        if total_chars + len(chunk.text) > _MAX_CANDIDATE_CHARS:
            break
        result_chunks.append(chunk)
        total_chars += len(chunk.text)

    logger.info(
        f"_select_candidate_chunks: {len(result_chunks)}/{len(chunk_list)} chunks valgt, "
        f"{total_chars} tegn, max_score={max_score}"
    )
    for s, i, reasons in scored:
        if s > 0:
            logger.debug(f"  chunk[{i}] score={s} reasons={reasons}")

    return result_chunks


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _enrich_from_doc(
    doc_id: str,
    chunk_list: List[Chunk],
    canonical_list: List[Servitut],
    all_matrikler: List[str],
    progress_callback: Optional[ProgressCallback],
    doc_filename: Optional[str] = None,
) -> List[dict]:
    """One LLM call per akt: ask which canonical servitutter it contains.
    chunk_list should already be pre-filtered candidate chunks (Fase 1).
    """
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
            progress_callback,
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
    doc_filename_by_id: Optional[dict[str, str]] = None,
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
    # Byg akt_nr → liste af canonical keys (et akt_nr kan referere til flere servitutter
    # der deler samme fysiske arkivskab, f.eks. 40_C_239 → 1903 + 1975)
    canonical_by_akt: dict[str, list[str]] = {}
    for s in canonical_list:
        if s.akt_nr:
            key = _normalize_akt_nr(s.akt_nr)
            canonical_by_akt.setdefault(key, []).append(s.date_reference or "")
    # Year-frequency table for fuzzy matching (unambiguous year → 1 match)
    canonical_years: dict[str, int] = {}
    for s in canonical_list:
        y = _extract_date_components(s.date_reference).get("year")
        if y:
            canonical_years[y] = canonical_years.get(y, 0) + 1
    # key (canonical date_reference) → (best item dict, doc_id, chunk_list, priority)
    # priority 1=akt_nr match, 2=exact date, 3=fuzzy date — lower = better
    best_by_key: dict[str, tuple[dict, str, List[Chunk], int]] = {}
    # orphan_key → (item, doc_id, chunk_list) — fundet i akt men ikke i attest
    orphan_best: dict[str, tuple[dict, str, List[Chunk]]] = {}

    # --- Fase 1: Deterministisk chunk-filtrering ---
    logger.info("Fase 1: Scorer og filtrerer akt-chunks mod canonical-signaler")
    candidate_chunks_by_doc: dict[str, list[Chunk]] = {}
    for doc_id, chunk_list in akt_chunks_by_doc.items():
        candidates = _select_candidate_chunks(chunk_list, canonical_list)
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

    # --- Fase 2: LLM enrichment (kun docs med kandidater) ---
    for doc_id, chunk_list in candidate_chunks_by_doc.items():
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
            doc_filename=doc_filename_by_id.get(doc_id) if doc_filename_by_id else None,
        )

        for item in items:
            result_key = _resolve_canonical_key(item, canonical_by_date, canonical_by_akt, canonical_list, canonical_years)
            if result_key is None:
                # Ikke i tinglysningsattest — gem som ubekræftet
                orphan_key = _normalize_akt_nr(item.get("akt_nr") or "") or (item.get("date_reference") or "")
                if orphan_key and orphan_key not in orphan_best:
                    orphan_best[orphan_key] = (item, doc_id, chunk_list)
                elif orphan_key:
                    existing_conf = float(orphan_best[orphan_key][0].get("confidence", 0))
                    if float(item.get("confidence", 0.5) or 0.5) > existing_conf:
                        orphan_best[orphan_key] = (item, doc_id, chunk_list)
                logger.debug(
                    f"Umatched enrichment item (not in attest): "
                    f"date={item.get('date_reference')!r}, akt_nr={item.get('akt_nr')!r}"
                )
                continue
            key, priority = result_key
            item_conf = float(item.get("confidence", 0.5) or 0.5)
            existing = best_by_key.get(key)
            if existing is None:
                best_by_key[key] = (item, doc_id, chunk_list, priority)
            else:
                existing_conf = float(existing[0].get("confidence", 0))
                existing_priority = existing[3]
                # Lower priority number = better match; confidence breaks ties
                if priority < existing_priority or (priority == existing_priority and item_conf > existing_conf):
                    best_by_key[key] = (item, doc_id, chunk_list, priority)

    # Apply enrichments
    result: List[Servitut] = []
    matched = 0
    for canonical in canonical_list:
        key = canonical.date_reference or ""
        entry = best_by_key.get(key)
        if entry:
            item, doc_id, chunk_list, _priority = entry
            enriched_date = coerce_optional_str(item.get("date_reference")) or canonical.date_reference
            enriched_akt_nr = coerce_optional_str(item.get("akt_nr")) or canonical.akt_nr
            applies_to_matrikler = coerce_str_list(item.get("applies_to_matrikler"))
            akt_srv = Servitut(
                servitut_id=generate_servitut_id(),
                case_id=case_id,
                source_document=doc_id,
                date_reference=enriched_date,
                registered_at=parse_registered_at(item.get("registered_at"), enriched_date),
                akt_nr=enriched_akt_nr,
                title=coerce_optional_str(item.get("title")) or canonical.title,
                summary=coerce_optional_str(item.get("summary")),
                beneficiary=coerce_optional_str(item.get("beneficiary")),
                disposition_type=coerce_optional_str(item.get("disposition_type")),
                legal_type=coerce_optional_str(item.get("legal_type")),
                construction_relevance=bool(item.get("construction_relevance", False)),
                byggeri_markering=coerce_optional_str(item.get("byggeri_markering")),
                action_note=coerce_optional_str(item.get("action_note")),
                applies_to_matrikler=applies_to_matrikler,
                raw_matrikel_references=coerce_str_list(item.get("raw_matrikel_references"))
                or applies_to_matrikler,
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

    # Tilføj ubekræftede servitutter (fundet i akt, ikke i attest)
    unconfirmed_count = 0
    for orphan_key, (item, doc_id, chunk_list) in orphan_best.items():
        enriched_date = coerce_optional_str(item.get("date_reference"))
        enriched_akt_nr = coerce_optional_str(item.get("akt_nr"))
        srv = Servitut(
            servitut_id=generate_servitut_id(),
            case_id=case_id,
            source_document=doc_id,
            date_reference=enriched_date,
            registered_at=parse_registered_at(item.get("registered_at"), enriched_date),
            akt_nr=enriched_akt_nr,
            title=coerce_optional_str(item.get("title")),
            summary=coerce_optional_str(item.get("summary")),
            beneficiary=coerce_optional_str(item.get("beneficiary")),
            disposition_type=coerce_optional_str(item.get("disposition_type")),
            legal_type=coerce_optional_str(item.get("legal_type")),
            construction_relevance=bool(item.get("construction_relevance", False)),
            byggeri_markering=coerce_optional_str(item.get("byggeri_markering")),
            action_note=coerce_optional_str(item.get("action_note")),
            applies_to_matrikler=coerce_str_list(item.get("applies_to_matrikler")),
            raw_matrikel_references=coerce_str_list(item.get("raw_matrikel_references"))
            or coerce_str_list(item.get("applies_to_matrikler")),
            raw_scope_text=coerce_optional_str(item.get("raw_scope_text"))
            or coerce_optional_str(item.get("scope_basis")),
            scope_source=coerce_optional_str(item.get("scope_source")) or "akt",
            scope_basis=coerce_optional_str(item.get("scope_basis")),
            scope_confidence=item.get("scope_confidence"),
            confidence=float(item.get("confidence", 0.5) or 0.5),
            evidence=_make_akt_evidence(chunk_list, enriched_date, enriched_akt_nr),
            attest_confirmed=False,
        )
        result.append(srv)
        unconfirmed_count += 1
        logger.info(
            f"Ubekræftet servitut tilføjet (ikke i attest): {srv.title} ({srv.date_reference})"
        )

    logger.info(
        f"Enrichment færdig: {matched}/{len(canonical_list)} beriget, "
        f"{unconfirmed_count} ubekræftede fra akter"
    )
    return result
