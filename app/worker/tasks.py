from __future__ import annotations

from typing import Any

from celery.utils.log import get_task_logger

from app.db.database import get_session_ctx
from app.models.job import Job
from app.services import case_service, extraction_service, pipeline_observability, storage_service
from app.services.ocr_service import run_document_pipeline
from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)
_UNSET = object()


def _merge_result_data(existing: Any, update: Any) -> Any:
    if isinstance(existing, dict) and isinstance(update, dict):
        return {**existing, **update}
    return update


def _update_job(
    case_id: str,
    job_id: str,
    *,
    status: str | None = None,
    result_data: Any = _UNSET,
) -> Job:
    with get_session_ctx() as session:
        job = storage_service.load_job(session, case_id, job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")
        if status is not None:
            job.status = status
        if result_data is not _UNSET:
            job.result_data = _merge_result_data(job.result_data, result_data)
        storage_service.save_job(session, job)
        return job


def _job_progress_callback(case_id: str, job_id: str):
    def progress_callback(event: dict[str, Any]) -> None:
        _update_job(
            case_id,
            job_id,
            status="processing",
            result_data={
                "message": event.get("message"),
                "progress": event.get("progress"),
                "stage": event.get("stage"),
                "source_type": event.get("source_type"),
                "document_id": event.get("doc_id"),
                "worker": event.get("worker"),
                "servitut_count": event.get("servitut_count"),
                "last_event": event,
            },
        )

    return progress_callback


@celery_app.task(name="app.worker.tasks.run_ocr_task")
def run_ocr_task(job_id: str, case_id: str, doc_id: str) -> dict[str, Any]:
    _update_job(
        case_id,
        job_id,
        status="processing",
        result_data={"document_id": doc_id, "message": "OCR job started"},
    )

    try:
        with get_session_ctx() as session:
            doc = storage_service.load_document(session, case_id, doc_id)
            if doc is None:
                raise ValueError(f"Document not found: {doc_id}")

            doc.parse_status = "processing"
            storage_service.save_document(session, doc)

            result = run_document_pipeline(session, case_id, doc, run_id=job_id)
            payload = {
                "document_id": doc_id,
                "message": "OCR job completed",
                "page_count": len(result.pages),
                "chunk_count": len(result.chunks),
                "blank_pages": result.blank_pages,
                "low_conf_pages": result.low_conf_pages,
                "page_source": result.page_source,
                "direct_text_coverage": result.direct_text_coverage,
                "duration_seconds": result.total_duration_seconds,
                "observability_file": result.observability_path,
            }

        _update_job(case_id, job_id, status="completed", result_data=payload)
        return payload
    except Exception as exc:
        observability_path = pipeline_observability.write_ocr_run_summary(
            case_id,
            doc_id,
            {
                "pipeline": "ocr",
                "case_id": case_id,
                "document_id": doc_id,
                "job_id": job_id,
                "status": "failed",
                "error": str(exc),
            },
            run_id=f"{job_id}_failed",
        )
        with get_session_ctx() as session:
            doc = storage_service.load_document(session, case_id, doc_id)
            if doc is not None:
                doc.parse_status = "error"
                storage_service.save_document(session, doc)

        _update_job(
            case_id,
            job_id,
            status="failed",
            result_data={
                "document_id": doc_id,
                "message": "OCR job failed",
                "error": str(exc),
                "observability_file": str(observability_path),
            },
        )
        logger.exception("OCR job failed for case=%s doc=%s", case_id, doc_id)
        raise


@celery_app.task(name="app.worker.tasks.run_extraction_task")
def run_extraction_task(job_id: str, case_id: str) -> dict[str, Any]:
    all_chunks_count = 0
    _update_job(
        case_id,
        job_id,
        status="processing",
        result_data={"message": "Extraction job started"},
    )

    try:
        with get_session_ctx() as session:
            case_service.update_case_status(session, case_id, "extracting")
        progress_callback = _job_progress_callback(case_id, job_id)

        with get_session_ctx() as session:
            all_chunks = storage_service.load_all_chunks(session, case_id)
            all_chunks_count = len(all_chunks)
            if not all_chunks:
                raise ValueError("No chunks found — parse documents first")

            servitutter = extraction_service.extract_servitutter(
                session,
                all_chunks,
                case_id,
                progress_callback=progress_callback,
                observability_run_id=job_id,
            )

            storage_service.replace_servitutter(session, case_id, servitutter)

            case_service.update_case_status(session, case_id, "done")
            payload = {
                "message": "Extraction job completed",
                "servitut_count": len(servitutter),
            }

        observability_path = pipeline_observability.write_extraction_run_summary(
            case_id,
            {
                "pipeline": "extraction_job",
                "case_id": case_id,
                "job_id": job_id,
                "status": "completed",
                "chunk_count": all_chunks_count,
                "servitut_count": len(servitutter),
            },
            run_id=f"{job_id}_job",
        )
        payload["observability_file"] = str(observability_path)

        _update_job(case_id, job_id, status="completed", result_data=payload)
        return payload
    except Exception as exc:
        observability_path = pipeline_observability.write_extraction_run_summary(
            case_id,
            {
                "pipeline": "extraction_job",
                "case_id": case_id,
                "job_id": job_id,
                "status": "failed",
                "chunk_count": all_chunks_count,
                "error": str(exc),
            },
            run_id=f"{job_id}_job_failed",
        )
        with get_session_ctx() as session:
            case_service.update_case_status(session, case_id, "error")

        _update_job(
            case_id,
            job_id,
            status="failed",
            result_data={
                "message": "Extraction job failed",
                "error": str(exc),
                "observability_file": str(observability_path),
            },
        )
        logger.exception("Extraction job failed for case=%s", case_id)
        raise


@celery_app.task(name="app.worker.tasks.run_attest_extraction_task")
def run_attest_extraction_task(job_id: str, case_id: str) -> dict[str, Any]:
    all_chunks_count = 0
    _update_job(
        case_id,
        job_id,
        status="processing",
        result_data={"message": "Attest extraction job started"},
    )

    try:
        with get_session_ctx() as session:
            case_service.update_case_status(session, case_id, "extracting")
        progress_callback = _job_progress_callback(case_id, job_id)

        with get_session_ctx() as session:
            all_chunks = storage_service.load_all_chunks(session, case_id)
            all_chunks_count = len(all_chunks)
            if not all_chunks:
                raise ValueError("No chunks found — parse documents first")

            servitutter = extraction_service.extract_attest_servitutter(
                session,
                case_id,
                progress_callback=progress_callback,
            )

            storage_service.replace_servitutter(session, case_id, servitutter)
            case_service.update_case_status(session, case_id, "done")
            payload = {
                "message": "Attest extraction job completed",
                "servitut_count": len(servitutter),
            }

        observability_path = pipeline_observability.write_extraction_run_summary(
            case_id,
            {
                "pipeline": "extraction_attest_job",
                "case_id": case_id,
                "job_id": job_id,
                "status": "completed",
                "chunk_count": all_chunks_count,
                "servitut_count": len(servitutter),
            },
            run_id=f"{job_id}_job",
        )
        payload["observability_file"] = str(observability_path)

        _update_job(case_id, job_id, status="completed", result_data=payload)
        return payload
    except Exception as exc:
        observability_path = pipeline_observability.write_extraction_run_summary(
            case_id,
            {
                "pipeline": "extraction_attest_job",
                "case_id": case_id,
                "job_id": job_id,
                "status": "failed",
                "chunk_count": all_chunks_count,
                "error": str(exc),
            },
            run_id=f"{job_id}_job_failed",
        )
        with get_session_ctx() as session:
            case_service.update_case_status(session, case_id, "error")

        _update_job(
            case_id,
            job_id,
            status="failed",
            result_data={
                "message": "Attest extraction job failed",
                "error": str(exc),
                "observability_file": str(observability_path),
            },
        )
        logger.exception("Attest extraction job failed for case=%s", case_id)
        raise


@celery_app.task(name="app.worker.tasks.run_akt_extraction_task")
def run_akt_extraction_task(job_id: str, case_id: str) -> dict[str, Any]:
    all_chunks_count = 0
    _update_job(
        case_id,
        job_id,
        status="processing",
        result_data={"message": "Akt extraction job started"},
    )

    try:
        with get_session_ctx() as session:
            case_service.update_case_status(session, case_id, "extracting")
        progress_callback = _job_progress_callback(case_id, job_id)

        with get_session_ctx() as session:
            all_chunks = storage_service.load_all_chunks(session, case_id)
            all_chunks_count = len(all_chunks)
            if not all_chunks:
                raise ValueError("No chunks found — parse documents first")

            servitutter = extraction_service.extract_akt_servitutter(
                session,
                case_id,
                progress_callback=progress_callback,
                observability_run_id=job_id,
            )

            storage_service.replace_servitutter(session, case_id, servitutter)
            case_service.update_case_status(session, case_id, "done")
            payload = {
                "message": "Akt extraction job completed",
                "servitut_count": len(servitutter),
            }

        observability_path = pipeline_observability.write_extraction_run_summary(
            case_id,
            {
                "pipeline": "extraction_akt_job",
                "case_id": case_id,
                "job_id": job_id,
                "status": "completed",
                "chunk_count": all_chunks_count,
                "servitut_count": len(servitutter),
            },
            run_id=f"{job_id}_job",
        )
        payload["observability_file"] = str(observability_path)

        _update_job(case_id, job_id, status="completed", result_data=payload)
        return payload
    except Exception as exc:
        observability_path = pipeline_observability.write_extraction_run_summary(
            case_id,
            {
                "pipeline": "extraction_akt_job",
                "case_id": case_id,
                "job_id": job_id,
                "status": "failed",
                "chunk_count": all_chunks_count,
                "error": str(exc),
            },
            run_id=f"{job_id}_job_failed",
        )
        with get_session_ctx() as session:
            case_service.update_case_status(session, case_id, "error")

        _update_job(
            case_id,
            job_id,
            status="failed",
            result_data={
                "message": "Akt extraction job failed",
                "error": str(exc),
                "observability_file": str(observability_path),
            },
        )
        logger.exception("Akt extraction job failed for case=%s", case_id)
        raise
