from collections import Counter
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from app.api.dependencies.auth import get_current_user
from app.db.database import get_session
from app.models.attest import AttestDebugBlock, AttestDebugSegment, AttestPipelineDebug
from app.models.document import Document
from app.models.user import User
from app.services import case_service, storage_service
from app.services.document_service import create_document_from_bytes
from app.services.document_classifier import classify_document, validate_document_type

router = APIRouter()


@router.post("/{case_id}/documents", response_model=Document, status_code=201)
async def upload_document(
    case_id: str,
    file: UploadFile = File(...),
    document_type: str | None = Form(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    try:
        requested_type = validate_document_type(document_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_bytes = await file.read()
    doc = create_document_from_bytes(
        session=session,
        case_id=case_id,
        filename=file.filename or "document.pdf",
        file_bytes=file_bytes,
        document_type=classify_document(file.filename or "document.pdf", requested_type=requested_type),
    )
    return doc


@router.get("/{case_id}/documents", response_model=List[Document])
def list_documents(
    case_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    return storage_service.list_documents(
        session,
        case_id,
        owner_user_id=current_user.id,
    )


@router.get("/{case_id}/documents/{doc_id}", response_model=Document)
def get_document(
    case_id: str,
    doc_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    doc = storage_service.load_document(
        session,
        case_id,
        doc_id,
        owner_user_id=current_user.id,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{case_id}/documents/{doc_id}", status_code=204)
def delete_document(
    case_id: str,
    doc_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    doc = storage_service.load_document(
        session,
        case_id,
        doc_id,
        owner_user_id=current_user.id,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.parse_status != "pending":
        raise HTTPException(
            status_code=409,
            detail="Only documents that have not started OCR can be deleted",
        )

    case_service.remove_document_from_case(
        session,
        case_id,
        doc_id,
        owner_user_id=current_user.id,
    )


@router.get("/{case_id}/documents/{doc_id}/attest-debug", response_model=AttestPipelineDebug)
def get_attest_debug(
    case_id: str,
    doc_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    doc = storage_service.load_document(
        session,
        case_id,
        doc_id,
        owner_user_id=current_user.id,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.document_type != "tinglysningsattest":
        raise HTTPException(status_code=400, detail="Document is not a tinglysningsattest")

    state = storage_service.load_attest_pipeline_state(
        session,
        case_id,
        doc_id,
        owner_user_id=current_user.id,
    )
    if state is None:
        raise HTTPException(status_code=404, detail="Attest pipeline state not found")

    return AttestPipelineDebug(
        case_id=case_id,
        document_id=doc_id,
        filename=doc.filename,
        document_type=doc.document_type,
        version=state.version,
        segment_strategy=state.segment_strategy,
        page_count=state.page_count,
        segment_count=len(state.segments),
        declaration_block_count=len(state.declaration_blocks),
        unresolved_block_ids=list(state.unresolved_block_ids),
        unresolved_block_count=len(state.unresolved_block_ids),
        block_type_counts=dict(Counter(segment.block_type for segment in state.segments)),
        segments=[
            AttestDebugSegment(
                segment_id=segment.segment_id,
                segment_index=segment.segment_index,
                page_start=segment.page_start,
                page_end=segment.page_end,
                page_numbers=list(segment.page_numbers),
                heading=segment.heading,
                block_type=segment.block_type,
                candidate_date_references=list(segment.candidate_date_references),
                candidate_archive_numbers=list(segment.candidate_archive_numbers),
            )
            for segment in state.segments
        ],
        declaration_blocks=[
            AttestDebugBlock(
                block_id=block.block_id,
                page_start=block.page_start,
                page_end=block.page_end,
                priority_number=block.priority_number,
                title=block.title,
                archive_number=block.archive_number,
                status=block.status,
                has_aflysning=block.has_aflysning,
                source_segment_ids=list(block.source_segment_ids),
                raw_parcel_references=list(block.raw_parcel_references),
                fanout_date_reference_count=len(block.fanout_date_refs),
                fanout_date_references_sample=list(block.fanout_date_refs[:10]),
            )
            for block in state.declaration_blocks
        ],
    )
