from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.servitut import Evidence, Servitut
from app.services import storage_service
from app.services.llm_service import generate_text
from app.utils.ids import generate_servitut_id
from app.utils.text import has_servitut_keywords

logger = get_logger(__name__)


def _load_prompt(source_type: str = "akt") -> str:
    if source_type == "tinglysningsattest":
        path = settings.prompts_path / "extract_tinglysningsattest.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")
    return (settings.prompts_path / "extract_servitut.txt").read_text(encoding="utf-8")


def _prescreeen_chunks(chunks: List[Chunk]) -> List[Chunk]:
    relevant = [c for c in chunks if has_servitut_keywords(c.text, threshold=1)]
    logger.info(f"Pre-screening: {len(relevant)}/{len(chunks)} chunks pass keyword filter")
    return relevant


def _build_chunks_text(chunks: List[Chunk]) -> str:
    parts = []
    for c in chunks:
        parts.append(f"[Dok: {c.document_id} | Side {c.page} | Chunk {c.chunk_index}]\n{c.text}")
    return "\n\n---\n\n".join(parts)


def _parse_llm_response(response_text: str) -> list:
    text = response_text.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        logger.warning("No JSON array found in LLM response")
        return []
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        logger.debug(f"Raw response: {text[:500]}")
        return []


def _find_evidence_chunk(chunks: List[Chunk], doc_id: str) -> List[Evidence]:
    doc_chunks = [c for c in chunks if c.document_id == doc_id]
    return [
        Evidence(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            page=c.page,
            text_excerpt=c.text[:300],
        )
        for c in doc_chunks[:3]
    ]


def _extract_date_components(date_ref: Optional[str]) -> dict:
    """Udtræk år, dato og løbenummer fra date_reference til brug ved matching."""
    if not date_ref:
        return {}

    result = {}

    # Fuldt løbenummer: 09.02.1957-490-40
    lob = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})-(\d+(?:-\d+)+)", date_ref)
    if lob:
        raw_date = lob.group(1)
        parts = raw_date.split(".")
        result["full_date"] = f"{parts[0].zfill(2)}.{parts[1].zfill(2)}.{parts[2]}"
        result["løbenummer_suffix"] = lob.group(2)
        result["year"] = parts[2]
        return result

    # Dato uden løbenummer: 09.02.1957 eller 9/2 1957
    date_m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", date_ref)
    if date_m:
        d, m, y = date_m.groups()
        result["full_date"] = f"{d.zfill(2)}.{m.zfill(2)}.{y}"
        result["year"] = y
        return result

    # År alene
    year_m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", date_ref)
    if year_m:
        result["year"] = year_m.group(1)

    return result


def _servitut_matches(canonical: Servitut, akt_srv: Servitut) -> bool:
    """Returner True hvis akt_srv sandsynligvis er samme servitut som canonical."""
    c = _extract_date_components(canonical.date_reference)
    a = _extract_date_components(akt_srv.date_reference)

    if not c or not a:
        return False

    # Stærkt match: samme løbenummer-suffiks (fx "490-40")
    if c.get("løbenummer_suffix") and a.get("løbenummer_suffix"):
        return c["løbenummer_suffix"] == a["løbenummer_suffix"]

    # Middel match: samme normaliserede dato (dd.mm.yyyy)
    if c.get("full_date") and a.get("full_date"):
        return c["full_date"] == a["full_date"]

    return False


def _enrich_canonical(canonical: Servitut, akt_srv: Servitut) -> Servitut:
    """Berig canonical servitut med detaljer fra akt-udtrukket servitut."""
    updates: dict = {}

    if not canonical.beneficiary and akt_srv.beneficiary:
        updates["beneficiary"] = akt_srv.beneficiary
    if not canonical.disposition_type and akt_srv.disposition_type:
        updates["disposition_type"] = akt_srv.disposition_type
    if not canonical.legal_type and akt_srv.legal_type:
        updates["legal_type"] = akt_srv.legal_type
    if not canonical.action_note and akt_srv.action_note:
        updates["action_note"] = akt_srv.action_note
    # Foretræk akt's markering — akten har fuld tekst og giver bedre grundlag
    if akt_srv.byggeri_markering and akt_srv.byggeri_markering != "sort":
        updates["byggeri_markering"] = akt_srv.byggeri_markering
    elif not canonical.byggeri_markering and akt_srv.byggeri_markering:
        updates["byggeri_markering"] = akt_srv.byggeri_markering
    if akt_srv.construction_relevance:
        updates["construction_relevance"] = True

    # Foretræk den rigere beskrivelse
    if akt_srv.summary and (
        not canonical.summary or len(akt_srv.summary) > len(canonical.summary)
    ):
        updates["summary"] = akt_srv.summary

    updates["confidence"] = max(canonical.confidence, akt_srv.confidence)
    updates["evidence"] = canonical.evidence + akt_srv.evidence

    if updates:
        return canonical.model_copy(update=updates)
    return canonical


def _dedup_akt_servitutter(akt_list: List[Servitut]) -> List[Servitut]:
    """
    Dedupliker akt-udtrukte servitutter når ingen tinglysningsattest foreligger.
    Grupper på løbenummer/dato og behold den mest komplette per gruppe.
    """
    result: List[Servitut] = []
    used = set()

    for i, srv in enumerate(akt_list):
        if i in used:
            continue
        matches = [
            j for j, other in enumerate(akt_list)
            if j != i and j not in used and _servitut_matches(srv, other)
        ]
        if matches:
            group = [srv] + [akt_list[j] for j in matches]
            # Behold den med flest udfyldte felter og højest confidence
            best = max(group, key=lambda s: (
                sum(1 for f in [s.beneficiary, s.summary, s.disposition_type, s.legal_type, s.action_note] if f),
                s.confidence,
            ))
            result.append(best)
            used.update(matches)
        else:
            result.append(srv)
        used.add(i)

    logger.info(f"Dedup (fallback): {len(akt_list)} → {len(result)} servitutter")
    return result


def _merge_servitutter(
    canonical_list: List[Servitut], akt_list: List[Servitut]
) -> List[Servitut]:
    """
    Brug canonical_list (fra tinglysningsattest) som source of truth.
    Berig hvert canonical entry med bedste match fra akt_list.
    Akt-servitutter uden canonical match kasseres (deduplicering).
    """
    result = []
    for canonical in canonical_list:
        matches = [a for a in akt_list if _servitut_matches(canonical, a)]
        if matches:
            best = max(matches, key=lambda s: s.confidence)
            result.append(_enrich_canonical(canonical, best))
            logger.debug(
                f"Match: {canonical.date_reference} ← {best.source_document}"
            )
        else:
            result.append(canonical)
    discarded = len(akt_list) - sum(
        1 for a in akt_list if any(_servitut_matches(c, a) for c in canonical_list)
    )
    logger.info(f"Merge færdig: {len(result)} servitutter, {discarded} duplikater kasseret")
    return result


def _extract_from_doc_chunks(
    doc_chunks: dict[str, List[Chunk]],
    case_id: str,
    source_type: str,
) -> List[Servitut]:
    """Udtræk servitutter fra grupperede doc→chunks. Intern hjælpefunktion."""
    prompt_template = _load_prompt(source_type)
    ordered_doc_ids = list(doc_chunks.keys())
    max_workers = min(
        max(1, settings.EXTRACTION_MAX_CONCURRENCY),
        len(ordered_doc_ids),
    )

    if max_workers == 1:
        all_servitutter: List[Servitut] = []
        for doc_id in ordered_doc_ids:
            all_servitutter.extend(
                _extract_document_servitutter(
                    doc_id,
                    doc_chunks[doc_id],
                    case_id,
                    prompt_template,
                    source_type,
                )
            )
        return all_servitutter

    logger.info(
        f"Parallel extraction enabled for {len(ordered_doc_ids)} documents "
        f"(max_workers={max_workers}, type={source_type})"
    )
    results_by_doc: dict[str, List[Servitut]] = {}
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="extract-doc") as executor:
        futures = {
            executor.submit(
                _extract_document_servitutter,
                doc_id,
                doc_chunks[doc_id],
                case_id,
                prompt_template,
                source_type,
            ): doc_id
            for doc_id in ordered_doc_ids
        }
        for future in as_completed(futures):
            doc_id = futures[future]
            try:
                results_by_doc[doc_id] = future.result()
            except Exception as e:
                logger.error(f"Parallel extraction worker failed for doc {doc_id}: {e}")
                results_by_doc[doc_id] = []

    all_servitutter: List[Servitut] = []
    for doc_id in ordered_doc_ids:
        all_servitutter.extend(results_by_doc.get(doc_id, []))
    return all_servitutter


def _extract_document_servitutter(
    doc_id: str,
    chunk_list: List[Chunk],
    case_id: str,
    prompt_template: str,
    source_type: str,
) -> List[Servitut]:
    logger.info(
        f"Extracting from doc {doc_id} ({len(chunk_list)} chunks, type={source_type})"
    )
    chunks_text = _build_chunks_text(chunk_list)
    prompt = prompt_template.replace("{chunks_text}", chunks_text)

    try:
        response_text = generate_text(prompt, max_tokens=4096)
        extracted = _parse_llm_response(response_text)
    except Exception as e:
        logger.error(f"LLM extraction error for doc {doc_id}: {e}")
        return []

    servitutter: List[Servitut] = []
    for i, item in enumerate(extracted):
        srv_id = generate_servitut_id()
        evidence = _find_evidence_chunk(chunk_list, doc_id)
        servitut = Servitut(
            servitut_id=srv_id,
            case_id=case_id,
            source_document=doc_id,
            priority=i,
            date_reference=item.get("date_reference"),
            title=item.get("title"),
            summary=item.get("summary"),
            beneficiary=item.get("beneficiary"),
            disposition_type=item.get("disposition_type"),
            legal_type=item.get("legal_type"),
            construction_relevance=item.get("construction_relevance", False) or False,
            byggeri_markering=item.get("byggeri_markering"),
            action_note=item.get("action_note"),
            confidence=float(item.get("confidence", 0.5) or 0.5),
            evidence=evidence,
        )
        servitutter.append(servitut)
        logger.info(f"Extracted: {servitut.title} (conf={servitut.confidence})")

    return servitutter


def extract_servitutter(chunks: List[Chunk], case_id: str) -> List[Servitut]:
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
        akt_list = _extract_from_doc_chunks(doc_chunks, case_id, "akt")
        return _dedup_akt_servitutter(akt_list)

    # --- Pas 1: Tinglysningsattest ---
    logger.info(f"Pas 1: Udtræk fra tinglysningsattest ({len(attest_chunks)} chunks)")
    attest_by_doc: dict[str, list[Chunk]] = {}
    for c in attest_chunks:
        attest_by_doc.setdefault(c.document_id, []).append(c)
    canonical_list = _extract_from_doc_chunks(attest_by_doc, case_id, "tinglysningsattest")
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
        akt_list = _extract_from_doc_chunks(akt_by_doc, case_id, "akt")
        logger.info(f"Akt-udtræk: {len(akt_list)} servitutter")
    else:
        akt_list = []

    # --- Merge ---
    return _merge_servitutter(canonical_list, akt_list)
