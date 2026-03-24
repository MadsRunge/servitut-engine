"""Fan-out fra DeclarationBlock til RegistrationEntry (Servitut).

Trin 3 i attest-pipeline v2:
  DeclarationBlock → List[Servitut]  (én pr. gyldig date_reference)

Returnerer (entries, resolved):
  resolved=False → blokken havde ingen gyldige date_references.
  Sådanne blokke registreres som uafklarede og producerer ingen Servitut.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import List, Optional, Tuple

from app.core.logging import get_logger
from app.models.attest import DeclarationBlock
from app.models.servitut import Servitut

logger = get_logger(__name__)

_DATE_REFERENCE_PATTERN = re.compile(r"\b\d{2}\.\d{2}\.\d{4}-[0-9A-Za-z./-]+\b")
_PARCEL_PATTERN = re.compile(r"\b\d+[a-zæøå]{0,3}\b", re.IGNORECASE)

# Normalisering: DD.MM.YYYY-NNNNNN varianter
_DATE_REF_NORMALIZE = re.compile(
    r"(\d{2})[.\-/](\d{2})[.\-/](\d{4})\s*[-/]\s*([0-9A-Za-z./-]+)"
)


def validate_date_reference(raw: str) -> Optional[str]:
    """Normaliser rå date_reference til kanonisk form.

    Returnér None hvis formatet er ugyldigt.
    Accepterede inputformater:
      DD.MM.YYYY-NNNNNN
      DD.MM.YYYY - NNNNNN
      DD-MM-YYYY/NNNNNN
    """
    if not raw:
        return None
    m = _DATE_REF_NORMALIZE.search(raw.strip())
    if not m:
        return None
    day, month, year, lob = m.group(1), m.group(2), m.group(3), m.group(4)
    # Basale sanity checks
    try:
        date(int(year), int(month), int(day))
    except ValueError:
        return None
    lob_clean = re.sub(r"\s+", "", lob)
    if not lob_clean:
        return None
    return f"{year}{month}{day}-{lob_clean}"


def _parse_registered_at(raw: str) -> Optional[date]:
    m = _DATE_REF_NORMALIZE.search(raw)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _entry_id(doc_id: str, date_reference: str) -> str:
    payload = f"{doc_id}:{date_reference}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _block_entry_id(doc_id: str, block_id: str) -> str:
    payload = f"{doc_id}:block:{block_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _deduplicated(refs: List[str]) -> List[str]:
    seen: dict[str, None] = {}
    for r in refs:
        seen[r] = None
    return list(seen.keys())


def _extract_per_ref_parcel_refs(block: DeclarationBlock) -> dict[str, List[str]]:
    """Udtræk parcel-referencer pr. date_reference fra FANOUT-tekst.

    Returnerer en dict: {date_ref: [parcel, ...]}
    Kun udfyldt hvis parcel-refs optræder i nærheden af date_ref i teksten.
    """
    result: dict[str, List[str]] = {}
    text = block.raw_scope_text
    if not text:
        return result

    lines = text.splitlines()
    for i, line in enumerate(lines):
        date_refs_in_line = _DATE_REFERENCE_PATTERN.findall(line)
        if not date_refs_in_line:
            continue
        # Søg i samme linje og ±2 linjer for parcel-refs
        context = "\n".join(lines[max(0, i - 2):i + 3])
        parcel_refs = [m.group(0).lower() for m in _PARCEL_PATTERN.finditer(context)]
        for ref in date_refs_in_line:
            if parcel_refs:
                result.setdefault(ref, []).extend(parcel_refs)
    return result


def _build_entry(
    block: DeclarationBlock,
    case_id: str,
    date_reference: str,
    is_fanout: bool,
    raw_scope_text: Optional[str],
    scope_confidence: float,
) -> Servitut:
    registered_at = _parse_registered_at(date_reference)
    return Servitut(
        easement_id=_entry_id(block.document_id, date_reference),
        case_id=case_id,
        source_document=block.document_id,
        priority=0,
        date_reference=date_reference,
        registered_at=registered_at,
        archive_number=block.archive_number,
        title=block.title,
        applies_to_parcel_numbers=[],
        raw_parcel_references=block.raw_parcel_references,
        applies_to_primary_parcel=None,
        raw_scope_text=raw_scope_text or block.raw_scope_text or "",
        scope_source="attest",
        scope_confidence=scope_confidence,
        confirmed_by_attest=True,
        # Pipeline v2 felter
        status=block.status,
        is_fanout_entry=is_fanout,
        declaration_block_id=block.block_id,
    )


def fan_out_registration_entries(
    block: DeclarationBlock,
    case_id: str,
) -> Tuple[List[Servitut], bool]:
    """Materialisér RegistrationEntry-objekter (Servitut) fra en DeclarationBlock.

    Returnerer (entries, resolved).
    resolved=False hvis blokken ikke indeholder nogen gyldige date_references.
    """
    # Saml alle rå date_refs fra fanout-feltet + scope-tekst
    raw_candidates = _deduplicated(
        block.fanout_date_refs
        + _DATE_REFERENCE_PATTERN.findall(block.raw_scope_text)
    )

    # Validér og byg mapping: raw → normalized (behold raw til parcel-lookup)
    raw_to_normalized: dict[str, str] = {}
    for raw in raw_candidates:
        normalized = validate_date_reference(raw)
        if normalized:
            raw_to_normalized[raw] = normalized
        else:
            logger.warning(
                "Ugyldig date_reference %r i blok %s — ignoreres",
                raw,
                block.block_id,
            )

    # Dedupliker på normaliseret form; bevar én raw-nøgle per normaliseret ref
    normalized_to_raw: dict[str, str] = {}
    for raw, norm in raw_to_normalized.items():
        if norm not in normalized_to_raw:
            normalized_to_raw[norm] = raw

    valid_refs = list(normalized_to_raw.keys())

    if not valid_refs:
        logger.warning(
            "Blok %s (dok=%s, sider %d-%d) har ingen gyldige date_references — uafklaret",
            block.block_id,
            block.document_id,
            block.page_start,
            block.page_end,
        )
        return ([], False)

    if len(valid_refs) == 1:
        entry = _build_entry(
            block=block,
            case_id=case_id,
            date_reference=valid_refs[0],
            is_fanout=False,
            raw_scope_text=block.raw_scope_text,
            scope_confidence=0.0,  # Udfyldes af scope_resolver
        )
        return ([entry], True)

    # Fan-out (Aalborg-mønster)
    # per_ref_parcel_refs bruger RAW refs som nøgler
    per_ref_parcel_refs = _extract_per_ref_parcel_refs(block)

    # Tjek om nogen entries har divergerende parcel-referencer
    unique_parcel_sets = {
        frozenset(per_ref_parcel_refs.get(normalized_to_raw[norm], []))
        for norm in valid_refs
    }
    has_scope_divergence = len(unique_parcel_sets) > 1

    entries: List[Servitut] = []
    for norm_ref in valid_refs:
        raw_key = normalized_to_raw[norm_ref]
        own_refs = per_ref_parcel_refs.get(raw_key, [])
        if has_scope_divergence:
            # Divergerende scope → konservativ confidence
            scope_conf = 0.35
            raw_scope = block.raw_scope_text
        elif own_refs:
            scope_conf = 0.75
            raw_scope = " ".join(own_refs)
        else:
            scope_conf = 0.35  # Arvet fra blok
            raw_scope = block.raw_scope_text

        entry = _build_entry(
            block=block,
            case_id=case_id,
            date_reference=norm_ref,
            is_fanout=True,
            raw_scope_text=raw_scope,
            scope_confidence=scope_conf,
        )
        entries.append(entry)

    return (entries, True)
