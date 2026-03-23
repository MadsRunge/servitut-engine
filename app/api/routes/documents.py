from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from app.api.dependencies.auth import get_current_user
from app.db.database import get_session
from app.models.document import Document
from app.models.user import User
from app.services import case_service, storage_service
from app.services.document_service import create_document_from_bytes
from app.services.document_classifier import classify_document, validate_document_type

router = APIRouter()


@router.post("/{case_id}/documents", response_model=Document, status_code=201)
async def upload_document(
    case_id: str,
    file: UploadFile = File(...),
    document_type: str | None = Form(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    try:
        requested_type = validate_document_type(document_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_bytes = await file.read()
    doc = create_document_from_bytes(
        session=session,
        case_id=case_id,
        filename=file.filename or "document.pdf",
        file_bytes=file_bytes,
        document_type=classify_document(file.filename or "document.pdf", requested_type=requested_type),
    )
    return doc


@router.get("/{case_id}/documents", response_model=List[Document])
def list_documents(
    case_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    return storage_service.list_documents(
        session,
        case_id,
        owner_user_id=current_user.id,
    )


@router.get("/{case_id}/documents/{doc_id}", response_model=Document)
def get_document(
    case_id: str,
    doc_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    doc = storage_service.load_document(
        session,
        case_id,
        doc_id,
        owner_user_id=current_user.id,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc
