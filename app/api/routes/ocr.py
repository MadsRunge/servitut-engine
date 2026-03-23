from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.dependencies.auth import get_current_user
from app.db.database import get_session
from app.models.chunk import Chunk
from app.models.document import PageData
from app.models.job import Job
from app.models.user import User
from app.services import case_service, storage_service
from app.utils.ids import generate_job_id
from app.worker.tasks import run_ocr_task

router = APIRouter()


@router.post(
    "/{case_id}/documents/{doc_id}/ocr",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_ocr(
    case_id: str,
    doc_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Kør OCR-pipeline på et dokument:
    original.pdf → ocrmypdf → ocr.pdf → pdfplumber tekst → chunks
    """
    case_service.verify_case_ownership(session, case_id, current_user.id)
    doc = storage_service.load_document(
        session,
        case_id,
        doc_id,
        owner_user_id=current_user.id,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    job = Job(
        id=generate_job_id(),
        case_id=case_id,
        task_type="ocr",
        status="pending",
        result_data={
            "document_id": doc_id,
            "message": "OCR job queued",
        },
    )
    storage_service.save_job(session, job)

    try:
        doc.parse_status = "processing"
        storage_service.save_document(session, doc)
        run_ocr_task.delay(job.id, case_id, doc_id)
    except Exception as exc:
        doc.parse_status = "pending"
        storage_service.save_document(session, doc)
        job.status = "failed"
        job.result_data = {
            "document_id": doc_id,
            "message": "Failed to queue OCR job",
            "error": str(exc),
        }
        storage_service.save_job(session, job)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not queue OCR job",
        )

    return job


@router.get("/{case_id}/documents/{doc_id}/pages", response_model=List[PageData])
def get_pages(
    case_id: str,
    doc_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Returner OCR-sider for et dokument."""
    case_service.verify_case_ownership(session, case_id, current_user.id)
    doc = storage_service.load_document(
        session,
        case_id,
        doc_id,
        owner_user_id=current_user.id,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return storage_service.load_ocr_pages(
        session,
        case_id,
        doc_id,
        owner_user_id=current_user.id,
    )


@router.get("/{case_id}/documents/{doc_id}/chunks", response_model=List[Chunk])
def get_chunks(
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
    return storage_service.load_chunks(
        session,
        case_id,
        doc_id,
        owner_user_id=current_user.id,
    )
