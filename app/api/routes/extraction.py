from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.dependencies.auth import get_current_user
from app.db.database import get_session
from app.models.servitut import Servitut
from app.models.user import User
from app.services import case_service, storage_service
from app.services.extraction_service import extract_servitutter

router = APIRouter()


@router.post("/{case_id}/extract", response_model=List[Servitut])
def trigger_extraction(
    case_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case = case_service.verify_case_ownership(session, case_id, current_user.id)

    all_chunks = storage_service.load_all_chunks(
        session,
        case_id,
        owner_user_id=current_user.id,
    )
    if not all_chunks:
        raise HTTPException(status_code=400, detail="No chunks found — parse documents first")

    case_service.update_case_status(
        session,
        case_id,
        "extracting",
        owner_user_id=current_user.id,
    )

    try:
        servitutter = extract_servitutter(session, all_chunks, case_id)
    except Exception as e:
        case_service.update_case_status(
            session,
            case_id,
            "error",
            owner_user_id=current_user.id,
        )
        raise HTTPException(status_code=500, detail=str(e))

    for srv in servitutter:
        storage_service.save_servitut(session, srv)

    case_service.update_case_status(
        session,
        case_id,
        "done",
        owner_user_id=current_user.id,
    )
    return servitutter


@router.get("/{case_id}/servitutter", response_model=List[Servitut])
def list_servitutter(
    case_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    return storage_service.list_servitutter(
        session,
        case_id,
        owner_user_id=current_user.id,
    )
