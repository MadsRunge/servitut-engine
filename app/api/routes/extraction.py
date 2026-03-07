from typing import List

from fastapi import APIRouter, HTTPException

from app.models.servitut import Servitut
from app.services import case_service, storage_service
from app.services.extraction_service import extract_servitutter

router = APIRouter()


@router.post("/{case_id}/extract", response_model=List[Servitut])
def trigger_extraction(case_id: str):
    case = case_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    all_chunks = storage_service.load_all_chunks(case_id)
    if not all_chunks:
        raise HTTPException(status_code=400, detail="No chunks found — parse documents first")

    case_service.update_case_status(case_id, "extracting")

    try:
        servitutter = extract_servitutter(all_chunks, case_id)
    except Exception as e:
        case_service.update_case_status(case_id, "error")
        raise HTTPException(status_code=500, detail=str(e))

    for srv in servitutter:
        storage_service.save_servitut(srv)

    case_service.update_case_status(case_id, "done")
    return servitutter


@router.get("/{case_id}/servitutter", response_model=List[Servitut])
def list_servitutter(case_id: str):
    case = case_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return storage_service.list_servitutter(case_id)
