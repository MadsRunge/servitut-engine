from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db.database import get_session
from app.models.report import Report
from app.services import case_service, matrikel_service, storage_service
from app.services.report_service import generate_report

router = APIRouter()


@router.post("/{case_id}/reports", response_model=Report, status_code=201)
def create_report(
    case_id: str,
    as_of_date: date | None = Query(default=None),
    session: Session = Depends(get_session),
):
    case = case_service.get_case(session, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    case = matrikel_service.sync_case_matrikler(session, case_id) or case
    servitutter = storage_service.list_servitutter(session, case_id)
    if not servitutter:
        raise HTTPException(status_code=400, detail="No servitutter found — run extraction first")

    all_chunks = storage_service.load_all_chunks(session, case_id)

    try:
        target = [case.target_matrikel] if case.target_matrikel else []
        report = generate_report(
            session,
            servitutter,
            all_chunks,
            case_id,
            target_matrikler=target,
            available_matrikler=[matrikel.matrikelnummer for matrikel in case.matrikler],
            as_of_date=as_of_date,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    storage_service.save_report(session, report)
    return report


@router.get("/{case_id}/reports", response_model=List[Report])
def list_reports(case_id: str, session: Session = Depends(get_session)):
    case = case_service.get_case(session, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return storage_service.list_reports(session, case_id)


@router.get("/{case_id}/reports/{report_id}", response_model=Report)
def get_report(case_id: str, report_id: str, session: Session = Depends(get_session)):
    report = storage_service.load_report(session, case_id, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report
