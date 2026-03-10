import shutil
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.document import Document
from app.services import case_service, storage_service
from app.services.document_classifier import classify_document, validate_document_type
from app.utils.ids import generate_doc_id

router = APIRouter()


@router.post("/{case_id}/documents", response_model=Document, status_code=201)
async def upload_document(
    case_id: str,
    file: UploadFile = File(...),
    document_type: str | None = Form(default=None),
):
    case = case_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        requested_type = validate_document_type(document_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        document_type=classify_document(file.filename or "document.pdf", requested_type=requested_type),
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


@router.get("/{case_id}/documents/{doc_id}", response_model=Document)
def get_document(case_id: str, doc_id: str):
    doc = storage_service.load_document(case_id, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc
