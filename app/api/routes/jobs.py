from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.dependencies.auth import get_current_user
from app.db.database import get_session
from app.models.job import Job
from app.models.user import User
from app.services import case_service, storage_service

router = APIRouter()


@router.get("/{case_id}/jobs/{job_id}", response_model=Job)
def get_job_status(
    case_id: str,
    job_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    job = storage_service.load_job(
        session,
        case_id,
        job_id,
        owner_user_id=current_user.id,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
