import shutil
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models.chunk import Chunk
from app.models.document import Document
from app.services import case_service, storage_service
from app.services.chunking_service import chunk_pages
from app.services.pdf_service import parse_pdf
from app.utils.ids import generate_doc_id

router = APIRouter()


@router.post("/{case_id}/documents", response_model=Document, status_code=201)
async def upload_document(case_id: str, file: UploadFile = File(...)):
    case = case_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    doc_id = generate_doc_id()
    pdf_path = storage_service.get_document_pdf_path(case_id, doc_id)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    doc = Document(
        document_id=doc_id,
        case_id=case_id,
        filename=file.filename or "document.pdf",
        file_path=str(pdf_path),
        parse_status="pending",
    )
    storage_service.save_document(doc)
    case_service.add_document_to_case(case_id, doc_id)
    return doc


@router.get("/{case_id}/documents", response_model=List[Document])
def list_documents(case_id: str):
    case = case_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return storage_service.list_documents(case_id)


@router.post("/{case_id}/documents/{doc_id}/parse", response_model=Document)
def parse_document(case_id: str, doc_id: str):
    doc = storage_service.load_document(case_id, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    pdf_path = Path(doc.file_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=400, detail="PDF file not found on disk")

    try:
        pages = parse_pdf(pdf_path)
        doc.pages = pages
        doc.page_count = len(pages)
        doc.parse_status = "parsed"
        storage_service.save_document(doc)

        # Auto-chunk after parsing
        chunks = chunk_pages(pages, doc_id, case_id)
        storage_service.save_chunks(case_id, doc_id, chunks)
    except Exception as e:
        doc.parse_status = "error"
        storage_service.save_document(doc)
        raise HTTPException(status_code=500, detail=str(e))

    return doc


@router.get("/{case_id}/documents/{doc_id}/chunks", response_model=List[Chunk])
def get_chunks(case_id: str, doc_id: str):
    doc = storage_service.load_document(case_id, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return storage_service.load_chunks(case_id, doc_id)
