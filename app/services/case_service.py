from typing import List, Optional
from uuid import UUID

from sqlmodel import Session

from app.core.logging import get_logger
from app.models.case import Case
from app.services import matrikel_service, storage_service
from app.utils.ids import generate_case_id

logger = get_logger(__name__)


def create_case(
    session: Session,
    name: str,
    address: Optional[str] = None,
    external_ref: Optional[str] = None,
    user_id: UUID | None = None,
) -> Case:
    case = Case(
        case_id=generate_case_id(),
        user_id=user_id,
        name=name,
        address=address,
        external_ref=external_ref,
    )
    storage_service.save_case(session, case)
    logger.info(f"Created case {case.case_id}: {name}")
    return case


def get_case(
    session: Session,
    case_id: str,
    owner_user_id: UUID | None = None,
) -> Optional[Case]:
    return storage_service.load_case(session, case_id, owner_user_id=owner_user_id)


def list_cases(session: Session, owner_user_id: UUID | None = None) -> List[Case]:
    return storage_service.list_cases(session, owner_user_id=owner_user_id)


def delete_case(
    session: Session,
    case_id: str,
    owner_user_id: UUID | None = None,
) -> bool:
    return storage_service.delete_case(session, case_id, owner_user_id=owner_user_id)


def update_case_status(
    session: Session,
    case_id: str,
    status: str,
    owner_user_id: UUID | None = None,
) -> Optional[Case]:
    case = storage_service.load_case(session, case_id, owner_user_id=owner_user_id)
    if not case:
        return None
    case.status = status
    storage_service.save_case(session, case)
    return case


def remove_document_from_case(
    session: Session,
    case_id: str,
    doc_id: str,
    owner_user_id: UUID | None = None,
) -> None:
    """Sletter dokumentet og alle tilknyttede artefakter."""
    storage_service.delete_document(
        session,
        case_id,
        doc_id,
        owner_user_id=owner_user_id,
    )
    logger.info(f"Removed document {doc_id} from case {case_id}")


def add_document_to_case(
    session: Session,
    case_id: str,
    doc_id: str,
    owner_user_id: UUID | None = None,
) -> Optional[Case]:
    """Med relationel storage er document_ids afledt af Document-tabellen.
    Funktionen er beholdt til bagudkompatibilitet men skriver ikke til cases-tabellen."""
    return storage_service.load_case(session, case_id, owner_user_id=owner_user_id)


def sync_case_matrikler(
    session: Session,
    case_id: str,
    attest_doc_ids=None,
    owner_user_id: UUID | None = None,
) -> Optional[Case]:
    case = storage_service.load_case(session, case_id, owner_user_id=owner_user_id)
    if case is None:
        return None
    return matrikel_service.sync_case_matrikler(session, case_id, attest_doc_ids)


def update_target_matrikel(
    session: Session,
    case_id: str,
    matrikelnummer: str,
    owner_user_id: UUID | None = None,
) -> Optional[Case]:
    case = storage_service.load_case(session, case_id, owner_user_id=owner_user_id)
    if case is None:
        return None
    return matrikel_service.update_target_matrikel(session, case_id, matrikelnummer)
