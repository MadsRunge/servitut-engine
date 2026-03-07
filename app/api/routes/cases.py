from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.case import Case
from app.services import case_service

router = APIRouter()


class CreateCaseRequest(BaseModel):
    name: str
    address: Optional[str] = None
    external_ref: Optional[str] = None


@router.post("", response_model=Case, status_code=201)
def create_case(req: CreateCaseRequest):
    return case_service.create_case(req.name, req.address, req.external_ref)


@router.get("", response_model=List[Case])
def list_cases():
    return case_service.list_cases()


@router.get("/{case_id}", response_model=Case)
def get_case(case_id: str):
    case = case_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.delete("/{case_id}", status_code=204)
def delete_case(case_id: str):
    if not case_service.delete_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
