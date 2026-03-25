from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.api.dependencies.auth import get_current_user
from app.db.database import get_session
from app.models.document import Document
from app.models.job import Job
from app.models.servitut import Servitut
from app.models.user import User
from app.services import case_service, storage_service
from app.utils.ids import generate_job_id
from app.worker.tasks import (
    run_akt_extraction_task,
    run_attest_extraction_task,
    run_extraction_task,
)

router = APIRouter()


def _load_case_documents(
    session: Session,
    case_id: str,
    current_user: User,
) -> list[Document]:
    return storage_service.list_documents(
        session,
        case_id,
        owner_user_id=current_user.id,
    )


def _require_attest(documents: list[Document]) -> None:
    if not any(doc.document_type == "tinglysningsattest" for doc in documents):
        raise HTTPException(
            status_code=400,
            detail="No tinglysningsattest found — extraction requires the property's own attest",
        )


def _require_akt(documents: list[Document]) -> None:
    if not any(doc.document_type == "akt" for doc in documents):
        raise HTTPException(
            status_code=400,
            detail="No akt documents found — upload akt documents before extract-akt",
        )


def _load_all_case_chunks(
    session: Session,
    case_id: str,
    current_user: User,
):
    all_chunks = storage_service.load_all_chunks(
        session,
        case_id,
        owner_user_id=current_user.id,
    )
    if not all_chunks:
        raise HTTPException(status_code=400, detail="No chunks found — parse documents first")
    return all_chunks


def _enqueue_extraction_job(
    session: Session,
    *,
    case_id: str,
    task_type: str,
    message: str,
    chunk_count: int,
    queue_fn,
    result_data: dict | None = None,
) -> Job:
    job = Job(
        id=generate_job_id(),
        case_id=case_id,
        task_type=task_type,
        status="pending",
        result_data={
            "message": message,
            "chunk_count": chunk_count,
            **(result_data or {}),
        },
    )
    storage_service.save_job(session, job)
    queue_fn(job.id, case_id)
    return job


@router.post(
    "/{case_id}/extract",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_extraction(
    case_id: str,
    force_rebuild: bool = Query(default=False),
    clear_attest_pipeline: bool = Query(default=False),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)

    documents = _load_case_documents(session, case_id, current_user)
    _require_attest(documents)

    reset_summary: dict[str, int] | None = None
    if force_rebuild:
        reset_summary = storage_service.reset_case_extraction_outputs(
            session,
            case_id,
            clear_attest_pipeline=clear_attest_pipeline,
        )

    all_chunks = _load_all_case_chunks(session, case_id, current_user)

    try:
        case_service.update_case_status(
            session,
            case_id,
            "extracting",
            owner_user_id=current_user.id,
        )
        job = _enqueue_extraction_job(
            session,
            case_id=case_id,
            task_type="extraction",
            message="Extraction job queued",
            chunk_count=len(all_chunks),
            queue_fn=run_extraction_task.delay,
            result_data={
                "force_rebuild": force_rebuild,
                "clear_attest_pipeline": clear_attest_pipeline,
                "reset_summary": reset_summary,
            },
        )
    except Exception as exc:
        case_service.update_case_status(
            session,
            case_id,
            "created",
            owner_user_id=current_user.id,
        )
        job = Job(
            id=generate_job_id(),
            case_id=case_id,
            task_type="extraction",
            status="failed",
            result_data={
                "message": "Failed to queue extraction job",
                "chunk_count": len(all_chunks),
                "error": str(exc),
            },
        )
        storage_service.save_job(session, job)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not queue extraction job",
        )

    return job


@router.post(
    "/{case_id}/extract-attest",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_attest_extraction(
    case_id: str,
    force_rebuild: bool = Query(default=False),
    clear_attest_pipeline: bool = Query(default=False),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)

    documents = _load_case_documents(session, case_id, current_user)
    _require_attest(documents)

    reset_summary: dict[str, int] | None = None
    if force_rebuild:
        reset_summary = storage_service.reset_case_extraction_outputs(
            session,
            case_id,
            clear_attest_pipeline=clear_attest_pipeline,
        )

    all_chunks = _load_all_case_chunks(session, case_id, current_user)

    try:
        case_service.update_case_status(
            session,
            case_id,
            "extracting",
            owner_user_id=current_user.id,
        )
        job = _enqueue_extraction_job(
            session,
            case_id=case_id,
            task_type="extraction_attest",
            message="Attest extraction job queued",
            chunk_count=len(all_chunks),
            queue_fn=run_attest_extraction_task.delay,
            result_data={
                "force_rebuild": force_rebuild,
                "clear_attest_pipeline": clear_attest_pipeline,
                "reset_summary": reset_summary,
            },
        )
    except Exception as exc:
        case_service.update_case_status(
            session,
            case_id,
            "created",
            owner_user_id=current_user.id,
        )
        job = Job(
            id=generate_job_id(),
            case_id=case_id,
            task_type="extraction_attest",
            status="failed",
            result_data={
                "message": "Failed to queue attest extraction job",
                "chunk_count": len(all_chunks),
                "error": str(exc),
            },
        )
        storage_service.save_job(session, job)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not queue attest extraction job",
        )

    return job


@router.post(
    "/{case_id}/extract-akt",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_akt_extraction(
    case_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)

    documents = _load_case_documents(session, case_id, current_user)
    _require_attest(documents)
    _require_akt(documents)

    canonical_list = storage_service.load_canonical_list(
        session,
        case_id,
    )
    if not canonical_list:
        raise HTTPException(
            status_code=400,
            detail="No canonical attest list found — run extract-attest first",
        )

    all_chunks = _load_all_case_chunks(session, case_id, current_user)

    try:
        case_service.update_case_status(
            session,
            case_id,
            "extracting",
            owner_user_id=current_user.id,
        )
        job = _enqueue_extraction_job(
            session,
            case_id=case_id,
            task_type="extraction_akt",
            message="Akt extraction job queued",
            chunk_count=len(all_chunks),
            queue_fn=run_akt_extraction_task.delay,
            result_data={
                "canonical_count": len(canonical_list),
            },
        )
    except Exception as exc:
        case_service.update_case_status(
            session,
            case_id,
            "created",
            owner_user_id=current_user.id,
        )
        job = Job(
            id=generate_job_id(),
            case_id=case_id,
            task_type="extraction_akt",
            status="failed",
            result_data={
                "message": "Failed to queue akt extraction job",
                "chunk_count": len(all_chunks),
                "error": str(exc),
            },
        )
        storage_service.save_job(session, job)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not queue akt extraction job",
        )

    return job


@router.get("/{case_id}/servitutter", response_model=List[Servitut])
def list_servitutter(
    case_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    servitutter = storage_service.list_servitutter(
        session,
        case_id,
        owner_user_id=current_user.id,
    )
    return [srv for srv in servitutter if srv.confirmed_by_attest]
