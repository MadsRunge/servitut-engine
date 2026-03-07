from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException

from app.models.document import Document, PageData
from app.models.chunk import Chunk
from app.services import case_service, storage_service
from app.services.chunking_service import chunk_pages
from app.services.ocr_service import process_document

router = APIRouter()


@router.post("/{case_id}/documents/{doc_id}/ocr", response_model=Document)
def run_ocr(case_id: str, doc_id: str):
    """Run OCR on a document: render pages to images, extract text via Claude Vision, chunk."""
    doc = storage_service.load_document(case_id, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    pdf_path = storage_service.get_document_pdf_path(case_id, doc_id)
    if not pdf_path.exists():
        raise HTTPException(status_code=400, detail="PDF file not found on disk")

    images_dir = storage_service.get_page_images_dir(case_id, doc_id)

    try:
        pages = process_document(pdf_path, doc_id, case_id, images_dir)
        storage_service.save_ocr_pages(case_id, doc_id, pages)

        doc.pages = pages
        doc.page_count = len(pages)
        doc.parse_status = "ocr_done"
        storage_service.save_document(doc)

        chunks = chunk_pages(pages, doc_id, case_id)
        storage_service.save_chunks(case_id, doc_id, chunks)
    except Exception as e:
        doc.parse_status = "error"
        storage_service.save_document(doc)
        raise HTTPException(status_code=500, detail=str(e))

    return doc


@router.get("/{case_id}/documents/{doc_id}/pages", response_model=List[PageData])
def get_pages(case_id: str, doc_id: str):
    """Return OCR pages for a document."""
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
