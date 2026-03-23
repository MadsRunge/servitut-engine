from sqlmodel import Session

from app.models.document import Document
from app.services import storage_service
from app.utils.ids import generate_doc_id


def create_document_from_bytes(
    session: Session,
    case_id: str,
    filename: str,
    file_bytes: bytes,
    document_type: str,
    parse_status: str = "pending",
) -> Document:
    doc_id = generate_doc_id()
    pdf_path = storage_service.get_document_pdf_path(case_id, doc_id)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pdf_path, "wb") as file_handle:
        file_handle.write(file_bytes)

    doc = Document(
        document_id=doc_id,
        case_id=case_id,
        filename=filename,
        file_path=str(pdf_path),
        document_type=document_type,
        parse_status=parse_status,
    )
    storage_service.save_document(session, doc)
    return doc
