from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.dependencies.auth import get_current_user
from app.db.database import get_session
from app.models.job import Job
from app.models.servitut import Servitut
from app.models.user import User
from app.services import case_service, storage_service
from app.utils.ids import generate_job_id
from app.worker.tasks import run_extraction_task

router = APIRouter()


@router.post(
    "/{case_id}/extract",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_extraction(
    case_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)

    all_chunks = storage_service.load_all_chunks(
        session,
        case_id,
        owner_user_id=current_user.id,
    )
    if not all_chunks:
        raise HTTPException(status_code=400, detail="No chunks found — parse documents first")

    job = Job(
        id=generate_job_id(),
        case_id=case_id,
        task_type="extraction",
        status="pending",
        result_data={
            "message": "Extraction job queued",
            "chunk_count": len(all_chunks),
        },
    )
    storage_service.save_job(session, job)

    try:
        case_service.update_case_status(
            session,
            case_id,
            "extracting",
            owner_user_id=current_user.id,
        )
        run_extraction_task.delay(job.id, case_id)
    except Exception as exc:
        case_service.update_case_status(
            session,
            case_id,
            "created",
            owner_user_id=current_user.id,
        )
        job.status = "failed"
        job.result_data = {
            "message": "Failed to queue extraction job",
            "chunk_count": len(all_chunks),
            "error": str(exc),
        }
        storage_service.save_job(session, job)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not queue extraction job",
        )

    return job


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
