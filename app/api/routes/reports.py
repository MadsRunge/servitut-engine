from datetime import date, datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.api.dependencies.auth import get_current_user
from app.core.logging import get_logger
from app.db.database import get_session
from app.models.report import Report, ReportPatch
from app.models.user import User
from app.services import case_service, storage_service
from app.services.report_render_service import build_markdown_table
from app.services.report_service import generate_report

logger = get_logger(__name__)

router = APIRouter()


@router.post("/{case_id}/reports", response_model=Report, status_code=201)
def create_report(
    case_id: str,
    as_of_date: date | None = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case = case_service.verify_case_ownership(session, case_id, current_user.id)
    case = case_service.sync_case_matrikler(
        session,
        case_id,
        owner_user_id=current_user.id,
    ) or case
    servitutter = storage_service.list_servitutter(
        session,
        case_id,
        owner_user_id=current_user.id,
    )
    servitutter = [srv for srv in servitutter if srv.confirmed_by_attest]
    if not servitutter:
        raise HTTPException(status_code=400, detail="No servitutter found — run extraction first")

    all_chunks = storage_service.load_all_chunks(
        session,
        case_id,
        owner_user_id=current_user.id,
    )

    try:
        target = [case.primary_parcel_number] if case.primary_parcel_number else []
        report = generate_report(
            session,
            servitutter,
            all_chunks,
            case_id,
            target_parcel_numbers=target,
            available_parcel_numbers=[matrikel.parcel_number for matrikel in case.parcels],
            as_of_date=as_of_date,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    storage_service.save_report(session, report)
    return report


@router.get("/{case_id}/reports", response_model=List[Report])
def list_reports(
    case_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    return storage_service.list_reports(
        session,
        case_id,
        owner_user_id=current_user.id,
    )


@router.patch("/{case_id}/reports/{report_id}", response_model=Report)
def patch_report(
    case_id: str,
    report_id: str,
    body: ReportPatch,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    report = storage_service.load_report(
        session,
        case_id,
        report_id,
        owner_user_id=current_user.id,
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    entries = body.entries if body.entries is not None else report.entries
    notes = body.notes if body.notes is not None else report.notes
    markdown = build_markdown_table(entries) if entries else None
    updated = report.model_copy(update={
        "entries": entries,
        "notes": notes,
        "manually_edited": True,
        "edited_at": datetime.utcnow(),
        "markdown_content": markdown,
    })
    storage_service.save_report(session, updated)
    return updated


@router.get("/{case_id}/reports/{report_id}", response_model=Report)
def get_report(
    case_id: str,
    report_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    report = storage_service.load_report(
        session,
        case_id,
        report_id,
        owner_user_id=current_user.id,
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report
