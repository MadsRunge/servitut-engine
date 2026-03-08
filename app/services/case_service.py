from typing import List, Optional

from app.core.logging import get_logger
from app.models.case import Case
from app.services import matrikel_service, storage_service
from app.utils.ids import generate_case_id

logger = get_logger(__name__)


def create_case(name: str, address: Optional[str] = None, external_ref: Optional[str] = None) -> Case:
    case = Case(
        case_id=generate_case_id(),
        name=name,
        address=address,
        external_ref=external_ref,
    )
    storage_service.save_case(case)
    logger.info(f"Created case {case.case_id}: {name}")
    return case


def get_case(case_id: str) -> Optional[Case]:
    return storage_service.load_case(case_id)


def list_cases() -> List[Case]:
    return storage_service.list_cases()


def delete_case(case_id: str) -> bool:
    return storage_service.delete_case(case_id)


def update_case_status(case_id: str, status: str) -> Optional[Case]:
    case = storage_service.load_case(case_id)
    if not case:
        return None
    case.status = status
    storage_service.save_case(case)
    return case


def add_document_to_case(case_id: str, doc_id: str) -> Optional[Case]:
    case = storage_service.load_case(case_id)
    if not case:
        return None
    if doc_id not in case.document_ids:
        case.document_ids.append(doc_id)
        storage_service.save_case(case)
    return case


def sync_case_matrikler(case_id: str) -> Optional[Case]:
    return matrikel_service.sync_case_matrikler(case_id)


def update_target_matrikel(case_id: str, matrikelnummer: str) -> Optional[Case]:
    return matrikel_service.update_target_matrikel(case_id, matrikelnummer)
