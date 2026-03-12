from typing import List

from fastapi import APIRouter, HTTPException

from app.models.chunk import Chunk
from app.models.document import Document, PageData
from app.services import storage_service
from app.services.ocr_service import run_document_pipeline

router = APIRouter()


@router.post("/{case_id}/documents/{doc_id}/ocr", response_model=Document)
def run_ocr(case_id: str, doc_id: str):
    """
    Kør OCR-pipeline på et dokument:
    original.pdf → ocrmypdf → ocr.pdf → pdfplumber tekst → chunks
    """
    doc = storage_service.load_document(case_id, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        doc.parse_status = "processing"
        storage_service.save_document(doc)
        result = run_document_pipeline(case_id, doc)
        doc.pages = result.pages
        doc.chunk_count = len(result.chunks)
    except Exception as e:
        doc.parse_status = "error"
        storage_service.save_document(doc)
        raise HTTPException(status_code=500, detail=str(e))

    return doc


@router.get("/{case_id}/documents/{doc_id}/pages", response_model=List[PageData])
def get_pages(case_id: str, doc_id: str):
    """Returner OCR-sider for et dokument."""
    doc = storage_service.load_document(case_id, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return storage_service.load_ocr_pages(case_id, doc_id)


@router.get("/{case_id}/documents/{doc_id}/chunks", response_model=List[Chunk])
def get_chunks(case_id: str, doc_id: str):
    doc = storage_service.load_document(case_id, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return storage_service.load_chunks(case_id, doc_id)
