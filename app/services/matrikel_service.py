import re
from typing import Iterable, List, Optional

from sqlmodel import Session

from app.core.logging import get_logger
from app.models.case import Case, Matrikel
from app.models.servitut import Servitut
from app.services import storage_service

logger = get_logger(__name__)

_MATRIKEL_BLOCK_RE = re.compile(
    r"Landsejerlav:\s*(?P<cadastral_district>.+?)\s*"
    r"Matrikelnummer:\s*(?P<parcel_number>[0-9A-Za-z]+)\s*"
    r"Areal:\s*(?P<areal>[0-9]+)\s*m2",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_matrikelnummer(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None

    cleaned = "".join(value.strip().lower().split())
    if not cleaned:
        return None

    match = re.fullmatch(r"(?P<number>\d+)(?P<suffix>[a-z]*)", cleaned)
    if not match:
        return cleaned

    number = str(int(match.group("number")))
    return f"{number}{match.group('suffix')}"


def _normalize_target_matrikler(
    target_parcel_numbers: Optional[List[str] | str],
) -> List[str]:
    if target_parcel_numbers is None:
        return []
    if isinstance(target_parcel_numbers, str):
        target_parcel_numbers = [target_parcel_numbers]

    normalized: list[str] = []
    seen: set[str] = set()
    for parcel_number in target_parcel_numbers:
        key = _normalize_matrikelnummer(parcel_number)
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


def parse_matrikler_from_text(text: str) -> List[Matrikel]:
    parcels: list[Matrikel] = []
    seen: set[str] = set()

    for match in _MATRIKEL_BLOCK_RE.finditer(text):
        parcel_number = match.group("parcel_number").strip().lower()
        normalized = _normalize_matrikelnummer(parcel_number) or parcel_number
        if normalized in seen:
            continue
        seen.add(normalized)
        areal_text = match.group("areal").strip()
        parcels.append(
            Matrikel(
                parcel_number=parcel_number,
                cadastral_district=" ".join(match.group("cadastral_district").split()),
                area_sqm=int(areal_text) if areal_text.isdigit() else None,
            )
        )

    return parcels


def sync_case_matrikler(
    session: Session,
    case_id: str,
    attest_doc_ids: Optional[Iterable[str]] = None,
) -> Optional[Case]:
    case = storage_service.load_case(session, case_id)
    if not case:
        return None

    if attest_doc_ids is None:
        attest_doc_ids = [
            doc.document_id
            for doc in storage_service.list_documents(session, case_id)
            if doc.document_type == "tinglysningsattest"
        ]

    texts: list[str] = []
    for doc_id in attest_doc_ids:
        pages = storage_service.load_ocr_pages(session, case_id, doc_id)
        if pages:
            texts.append("\n".join(page.text for page in pages[:2]))

    if not texts:
        return case

    parsed = parse_matrikler_from_text("\n\n".join(texts))
    if not parsed:
        logger.debug("No parcels parsed from attest for case %s", case_id)
        return case

    case.parcels = parsed
    valid_targets = {
        normalized: matrikel.parcel_number
        for matrikel in parsed
        if (normalized := _normalize_matrikelnummer(matrikel.parcel_number))
    }
    current_target = _normalize_matrikelnummer(case.primary_parcel_number)
    if not current_target or current_target not in valid_targets:
        case.primary_parcel_number = parsed[0].parcel_number
    else:
        case.primary_parcel_number = valid_targets[current_target]
    storage_service.save_case(session, case)
    logger.info("Synced %s parcels for case %s", len(parsed), case_id)
    return case


def update_target_matrikel(
    session: Session, case_id: str, parcel_number: str
) -> Optional[Case]:
    case = storage_service.load_case(session, case_id)
    if not case:
        return None

    normalized = _normalize_matrikelnummer(parcel_number)
    if not normalized:
        return case

    valid_targets = {
        key: matrikel.parcel_number
        for matrikel in case.parcels
        if (key := _normalize_matrikelnummer(matrikel.parcel_number))
    }
    if valid_targets and normalized not in valid_targets:
        return case

    case.primary_parcel_number = valid_targets.get(normalized, parcel_number.strip().lower())
    storage_service.save_case(session, case)
    return case


def resolve_target_matrikel_scope(
    applies_to_parcel_numbers: List[str],
    target_parcel_numbers: List[str] | str,
    available_parcel_numbers: Optional[List[str]] = None,
) -> Optional[bool]:
    """
    Return True if ANY target matrikel is in applies_to_parcel_numbers.
    Return None (Måske) if applies_to_parcel_numbers contains only unrecognized numbers
    (likely historical/old matrikel numbers that don't appear in available_parcel_numbers).
    Return False only if the parcels are known but definitively not in target.
    """
    normalized_targets = set(_normalize_target_matrikler(target_parcel_numbers))
    if not normalized_targets:
        return None
    normalized_applies = {
        normalized
        for parcel_number in applies_to_parcel_numbers
        if (normalized := _normalize_matrikelnummer(parcel_number))
    }
    if not normalized_applies:
        return None
    if normalized_targets & normalized_applies:
        return True
    # If none of applies_to_parcel_numbers appear in available_parcel_numbers either,
    # they are likely old/historical numbers — return None (Måske) instead of False.
    if available_parcel_numbers:
        normalized_available = {
            normalized
            for parcel_number in available_parcel_numbers
            if (normalized := _normalize_matrikelnummer(parcel_number))
        }
        if not normalized_applies & normalized_available:
            return None
    return False


def resolve_matching_target_matrikler(
    applies_to_parcel_numbers: List[str],
    target_parcel_numbers: List[str] | str,
) -> List[str]:
    """Return which of the target parcels the servitut explicitly applies to."""
    normalized_applies = {
        normalized
        for parcel_number in applies_to_parcel_numbers
        if (normalized := _normalize_matrikelnummer(parcel_number))
    }
    raw_targets = [target_parcel_numbers] if isinstance(target_parcel_numbers, str) else target_parcel_numbers

    matches: list[str] = []
    for target in raw_targets:
        if not isinstance(target, str):
            continue
        cleaned = target.strip().lower()
        normalized = _normalize_matrikelnummer(cleaned)
        if normalized and normalized in normalized_applies and cleaned not in matches:
            matches.append(cleaned)
    return matches


def filter_servitutter_for_target(
    servitutter: List[Servitut],
    target_parcel_numbers: List[str] | str,
    available_parcel_numbers: Optional[List[str]] = None,
) -> List[Servitut]:
    """
    Annotate all servitutter with applies_to_primary_parcel computed dynamically.
    Returns ALL servitutter (Ja + Nej + Måske) — matching a real redegørelse.
    """
    normalized_targets = _normalize_target_matrikler(target_parcel_numbers)
    if not normalized_targets:
        return servitutter
    return [
        srv.model_copy(update={
            "applies_to_primary_parcel": resolve_target_matrikel_scope(
                srv.applies_to_parcel_numbers, normalized_targets, available_parcel_numbers
            )
        })
        for srv in servitutter
    ]
