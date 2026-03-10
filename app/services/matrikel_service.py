import re
from typing import Iterable, List, Optional

from app.core.logging import get_logger
from app.models.case import Case, Matrikel
from app.models.servitut import Servitut
from app.services import storage_service

logger = get_logger(__name__)

_MATRIKEL_BLOCK_RE = re.compile(
    r"Landsejerlav:\s*(?P<landsejerlav>.+?)\s*"
    r"Matrikelnummer:\s*(?P<matrikelnummer>[0-9A-Za-z]+)\s*"
    r"Areal:\s*(?P<areal>[0-9]+)\s*m2",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_target_matrikler(
    target_matrikler: Optional[List[str] | str],
) -> List[str]:
    if target_matrikler is None:
        return []
    if isinstance(target_matrikler, str):
        target_matrikler = [target_matrikler]
    return [m.strip().lower() for m in target_matrikler if isinstance(m, str) and m.strip()]


def parse_matrikler_from_text(text: str) -> List[Matrikel]:
    matrikler: list[Matrikel] = []
    seen: set[str] = set()

    for match in _MATRIKEL_BLOCK_RE.finditer(text):
        matrikelnummer = match.group("matrikelnummer").strip().lower()
        if matrikelnummer in seen:
            continue
        seen.add(matrikelnummer)
        areal_text = match.group("areal").strip()
        matrikler.append(
            Matrikel(
                matrikelnummer=matrikelnummer,
                landsejerlav=" ".join(match.group("landsejerlav").split()),
                areal_m2=int(areal_text) if areal_text.isdigit() else None,
            )
        )

    return matrikler


def sync_case_matrikler(case_id: str, attest_doc_ids: Optional[Iterable[str]] = None) -> Optional[Case]:
    case = storage_service.load_case(case_id)
    if not case:
        return None

    if attest_doc_ids is None:
        attest_doc_ids = [
            doc.document_id
            for doc in storage_service.list_documents(case_id)
            if doc.document_type == "tinglysningsattest"
        ]

    texts: list[str] = []
    for doc_id in attest_doc_ids:
        pages = storage_service.load_ocr_pages(case_id, doc_id)
        if pages:
            texts.append("\n".join(page.text for page in pages[:2]))

    if not texts:
        return case

    parsed = parse_matrikler_from_text("\n\n".join(texts))
    if not parsed:
        logger.debug("No matrikler parsed from attest for case %s", case_id)
        return case

    case.matrikler = parsed
    valid_targets = {matrikel.matrikelnummer for matrikel in parsed}
    if case.target_matrikel not in valid_targets:
        case.target_matrikel = parsed[0].matrikelnummer
    storage_service.save_case(case)
    logger.info("Synced %s matrikler for case %s", len(parsed), case_id)
    return case


def update_target_matrikel(case_id: str, matrikelnummer: str) -> Optional[Case]:
    case = storage_service.load_case(case_id)
    if not case:
        return None

    normalized = matrikelnummer.strip().lower()
    valid_targets = {matrikel.matrikelnummer for matrikel in case.matrikler}
    if valid_targets and normalized not in valid_targets:
        return case

    case.target_matrikel = normalized
    storage_service.save_case(case)
    return case


def resolve_target_matrikel_scope(
    applies_to_matrikler: List[str],
    target_matrikler: List[str] | str,
    available_matrikler: Optional[List[str]] = None,
) -> Optional[bool]:
    """
    Return True if ANY target matrikel is in applies_to_matrikler.
    Return None (Måske) if applies_to_matrikler contains only unrecognized numbers
    (likely historical/old matrikel numbers that don't appear in available_matrikler).
    Return False only if the matrikler are known but definitively not in target.
    """
    normalized_targets = set(_normalize_target_matrikler(target_matrikler))
    if not normalized_targets:
        return None
    normalized_applies = {m.strip().lower() for m in applies_to_matrikler if m.strip()}
    if not normalized_applies:
        return None
    if normalized_targets & normalized_applies:
        return True
    # If none of applies_to_matrikler appear in available_matrikler either,
    # they are likely old/historical numbers — return None (Måske) instead of False.
    if available_matrikler:
        normalized_available = {m.strip().lower() for m in available_matrikler if m.strip()}
        if not normalized_applies & normalized_available:
            return None
    return False


def resolve_matching_target_matrikler(
    applies_to_matrikler: List[str],
    target_matrikler: List[str] | str,
) -> List[str]:
    """Return which of the target matrikler the servitut explicitly applies to."""
    normalized_applies = {m.strip().lower() for m in applies_to_matrikler if m.strip()}
    normalized_targets = _normalize_target_matrikler(target_matrikler)
    return [m for m in normalized_targets if m in normalized_applies]


def filter_servitutter_for_target(
    servitutter: List[Servitut],
    target_matrikler: List[str] | str,
    available_matrikler: Optional[List[str]] = None,
) -> List[Servitut]:
    """
    Annotate all servitutter with applies_to_target_matrikel computed dynamically.
    Returns ALL servitutter (Ja + Nej + Måske) — matching a real redegørelse.
    """
    normalized_targets = _normalize_target_matrikler(target_matrikler)
    if not normalized_targets:
        return servitutter
    return [
        srv.model_copy(update={
            "applies_to_target_matrikel": resolve_target_matrikel_scope(
                srv.applies_to_matrikler, normalized_targets, available_matrikler
            )
        })
        for srv in servitutter
    ]
