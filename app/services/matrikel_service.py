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

    if case.target_matrikel and case.target_matrikel != normalized:
        case.status = "created"
    case.target_matrikel = normalized
    storage_service.save_case(case)
    return case


def resolve_target_matrikel_scope(
    applies_to_matrikler: List[str],
    target_matrikel: Optional[str],
) -> Optional[bool]:
    if not target_matrikel:
        return None

    normalized_target = target_matrikel.strip().lower()
    normalized_matrikler = [value.strip().lower() for value in applies_to_matrikler if value.strip()]
    if not normalized_matrikler:
        return None
    return normalized_target in normalized_matrikler


def extraction_is_stale(case: Optional[Case]) -> bool:
    if not case or not case.target_matrikel:
        return False
    return case.last_extracted_target_matrikel != case.target_matrikel


def mark_extraction_target(case_id: str, target_matrikel: Optional[str]) -> Optional[Case]:
    case = storage_service.load_case(case_id)
    if not case:
        return None
    case.last_extracted_target_matrikel = target_matrikel.strip().lower() if target_matrikel else None
    storage_service.save_case(case)
    return case


def filter_servitutter_for_target(
    servitutter: List[Servitut],
    target_matrikel: Optional[str],
) -> List[Servitut]:
    if not target_matrikel:
        return servitutter
    return [srv for srv in servitutter if srv.applies_to_target_matrikel is not False]
