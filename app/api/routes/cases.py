from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.db.database import get_session
from app.models.case import Case
from app.services import case_service

router = APIRouter()


class CreateCaseRequest(BaseModel):
    name: str
    address: Optional[str] = None
    external_ref: Optional[str] = None


@router.post("", response_model=Case, status_code=201)
def create_case(req: CreateCaseRequest, session: Session = Depends(get_session)):
    return case_service.create_case(session, req.name, req.address, req.external_ref)


@router.get("", response_model=List[Case])
def list_cases(session: Session = Depends(get_session)):
    return case_service.list_cases(session)


@router.get("/{case_id}", response_model=Case)
def get_case(case_id: str, session: Session = Depends(get_session)):
    case = case_service.get_case(session, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.delete("/{case_id}", status_code=204)
def delete_case(case_id: str, session: Session = Depends(get_session)):
    if not case_service.delete_case(session, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
