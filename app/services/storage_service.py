"""
Persistenslag — alle læse/skriveoperationer går gennem dette modul.

Strukturerede data (sager, dokumenter, chunks, servitutter, rapporter, jobs)
gemmes i PostgreSQL via SQLModel. PDF-filer og side-billeder forbliver på disk;
OCR-sider skrives til JSONB på DocumentTable OG til disk (bruges af ocr_service
til mtime-baseret friskhedstjek).
"""

import shutil
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete
from sqlmodel import Session, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import (
    CaseTable,
    ChunkTable,
    DocumentTable,
    JobTable,
    ReportTable,
    ServitutTable,
    ServituterklaeringTable,
    TmvJobTable,
)
from app.models.case import Case, Matrikel
from app.models.chunk import Chunk
from app.models.attest import AttestPipelineState
from app.models.document import Document, PageData
from app.models.job import Job
from app.models.declaration import Servituterklaring, ServituterklaeringRow
from app.models.report import Report, ReportEntry
from app.models.servitut import Evidence, Servitut
from app.models.tmv_job import TmvJob
from app.utils.files import save_json

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Disk-stier til binære artefakter (forbliver fil-baserede)
# ---------------------------------------------------------------------------

def _case_dir(case_id: str) -> Path:
    return settings.cases_path / case_id


def _doc_dir(case_id: str, doc_id: str) -> Path:
    return _case_dir(case_id) / "documents" / doc_id


def get_ocr_pdf_path(case_id: str, doc_id: str) -> Path:
    """Sti til OCR-behandlet PDF (canonical OCR-artifact)."""
    return _doc_dir(case_id, doc_id) / "ocr.pdf"


def get_ocr_path(case_id: str, doc_id: str) -> Path:
    """Sti til OCR-sider på disk (bruges til mtime-friskhedstjek)."""
    return _case_dir(case_id) / "ocr" / f"{doc_id}_pages.json"


def get_document_pdf_path(case_id: str, doc_id: str) -> Path:
    return _doc_dir(case_id, doc_id) / "original.pdf"


def get_chunks_path(case_id: str, doc_id: str) -> Path:
    """Returneret til bagudkompatibilitet; chunks gemmes nu i DB."""
    return _case_dir(case_id) / "chunks" / f"{doc_id}_chunks.json"


# ---------------------------------------------------------------------------
# Konverteringsfunktioner
# ---------------------------------------------------------------------------

def _case_to_row(case: Case) -> CaseTable:
    d = case.model_dump(mode="json")
    return CaseTable(
        case_id=d["case_id"],
        user_id=case.user_id,
        name=d["name"],
        address=d.get("address"),
        external_ref=d.get("external_ref"),
        created_at=case.created_at,
        primary_parcel_number=d.get("primary_parcel_number"),
        last_extracted_primary_parcel_number=d.get("last_extracted_primary_parcel_number"),
        status=d.get("status", "created"),
        parcels=d.get("parcels") or [],
    )


def _row_to_case(row: CaseTable, document_ids: List[str]) -> Case:
    parcels = [Matrikel(**m) for m in (row.parcels or [])]
    return Case(
        case_id=row.case_id,
        user_id=row.user_id,
        name=row.name,
        address=row.address,
        external_ref=row.external_ref,
        created_at=row.created_at,
        primary_parcel_number=row.primary_parcel_number,
        last_extracted_primary_parcel_number=row.last_extracted_primary_parcel_number,
        status=row.status,
        parcels=parcels,
        document_ids=document_ids,
    )


def _doc_to_row(doc: Document) -> DocumentTable:
    d = doc.model_dump(mode="json")
    return DocumentTable(
        document_id=d["document_id"],
        case_id=d["case_id"],
        filename=d["filename"],
        file_path=d["file_path"],
        document_type=d.get("document_type", "unknown"),
        created_at=doc.created_at,
        page_count=d.get("page_count", 0),
        chunk_count=d.get("chunk_count", 0),
        ocr_blank_pages=d.get("ocr_blank_pages", 0),
        ocr_low_conf_pages=d.get("ocr_low_conf_pages", 0),
        parse_status=d.get("parse_status", "pending"),
        pages=d.get("pages") or [],
    )


def _row_to_doc(row: DocumentTable, include_pages: bool = True) -> Document:
    pages: List[PageData] = []
    if include_pages and row.pages:
        pages = [PageData(**p) for p in row.pages]
    return Document(
        document_id=row.document_id,
        case_id=row.case_id,
        filename=row.filename,
        file_path=row.file_path,
        document_type=row.document_type,
        created_at=row.created_at,
        page_count=row.page_count,
        chunk_count=row.chunk_count,
        ocr_blank_pages=row.ocr_blank_pages,
        ocr_low_conf_pages=row.ocr_low_conf_pages,
        parse_status=row.parse_status,
        pages=pages,
    )


def _chunk_to_row(chunk: Chunk) -> ChunkTable:
    return ChunkTable(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        case_id=chunk.case_id,
        page=chunk.page,
        text=chunk.text,
        chunk_index=chunk.chunk_index,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
    )


def _row_to_chunk(row: ChunkTable) -> Chunk:
    return Chunk(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        case_id=row.case_id,
        page=row.page,
        text=row.text,
        chunk_index=row.chunk_index,
        char_start=row.char_start,
        char_end=row.char_end,
    )


def _servitut_to_row(srv: Servitut) -> ServitutTable:
    d = srv.model_dump(mode="json")
    return ServitutTable(
        easement_id=d["easement_id"],
        case_id=d["case_id"],
        source_document=d["source_document"],
        priority=d.get("priority", 0),
        date_reference=d.get("date_reference"),
        registered_at=srv.registered_at,
        archive_number=d.get("archive_number"),
        title=d.get("title"),
        summary=d.get("summary"),
        beneficiary=d.get("beneficiary"),
        disposition_type=d.get("disposition_type"),
        legal_type=d.get("legal_type"),
        relevance_for_property=d.get("relevance_for_property"),
        construction_relevance=d.get("construction_relevance", False),
        construction_impact=d.get("construction_impact"),
        action_note=d.get("action_note"),
        applies_to_primary_parcel=d.get("applies_to_primary_parcel"),
        raw_scope_text=d.get("raw_scope_text"),
        scope_source=d.get("scope_source"),
        scope_basis=d.get("scope_basis"),
        scope_confidence=d.get("scope_confidence"),
        confidence=d.get("confidence", 0.0),
        confirmed_by_attest=d.get("confirmed_by_attest", True),
        review_status=d.get("review_status"),
        review_remarks=d.get("review_remarks"),
        status=d.get("status", "ukendt"),
        scope_type=d.get("scope_type"),
        is_fanout_entry=d.get("is_fanout_entry", False),
        declaration_block_id=d.get("declaration_block_id"),
        applies_to_parcel_numbers=d.get("applies_to_parcel_numbers") or [],
        raw_parcel_references=d.get("raw_parcel_references") or [],
        evidence=d.get("evidence") or [],
        flags=d.get("flags") or [],
    )


def _row_to_servitut(row: ServitutTable) -> Servitut:
    evidence = [Evidence(**e) for e in (row.evidence or [])]
    return Servitut(
        easement_id=row.easement_id,
        case_id=row.case_id,
        source_document=row.source_document,
        priority=row.priority,
        date_reference=row.date_reference,
        registered_at=row.registered_at,
        archive_number=row.archive_number,
        title=row.title,
        summary=row.summary,
        beneficiary=row.beneficiary,
        disposition_type=row.disposition_type,
        legal_type=row.legal_type,
        relevance_for_property=row.relevance_for_property,
        construction_relevance=row.construction_relevance,
        construction_impact=row.construction_impact,
        action_note=row.action_note,
        applies_to_primary_parcel=row.applies_to_primary_parcel,
        raw_scope_text=row.raw_scope_text,
        scope_source=row.scope_source,
        scope_basis=row.scope_basis,
        scope_confidence=row.scope_confidence,
        confidence=row.confidence,
        confirmed_by_attest=row.confirmed_by_attest,
        review_status=row.review_status,
        review_remarks=row.review_remarks,
        status=row.status,
        scope_type=row.scope_type,
        is_fanout_entry=row.is_fanout_entry,
        declaration_block_id=row.declaration_block_id,
        applies_to_parcel_numbers=list(row.applies_to_parcel_numbers or []),
        raw_parcel_references=list(row.raw_parcel_references or []),
        evidence=evidence,
        flags=list(row.flags or []),
    )


def _job_to_row(job: Job) -> JobTable:
    d = job.model_dump(mode="json")
    return JobTable(
        id=d["id"],
        case_id=d["case_id"],
        task_type=d["task_type"],
        status=d["status"],
        result_data=d.get("result_data"),
    )


def _row_to_job(row: JobTable) -> Job:
    return Job(
        id=row.id,
        case_id=row.case_id,
        task_type=row.task_type,
        status=row.status,
        result_data=row.result_data,
    )


def _report_to_row(report: Report) -> ReportTable:
    d = report.model_dump(mode="json")
    return ReportTable(
        report_id=d["report_id"],
        case_id=d["case_id"],
        created_at=report.created_at,
        edited_at=report.edited_at,
        manually_edited=d.get("manually_edited", False),
        as_of_date=report.as_of_date,
        notes=d.get("notes"),
        markdown_content=d.get("markdown_content"),
        target_parcel_numbers=d.get("target_parcel_numbers") or [],
        available_parcel_numbers=d.get("available_parcel_numbers") or [],
        entries=d.get("entries") or [],
    )


def _row_to_report(row: ReportTable) -> Report:
    entries = [ReportEntry(**e) for e in (row.entries or [])]
    return Report(
        report_id=row.report_id,
        case_id=row.case_id,
        created_at=row.created_at,
        edited_at=row.edited_at,
        manually_edited=row.manually_edited,
        as_of_date=row.as_of_date,
        notes=row.notes,
        markdown_content=row.markdown_content,
        target_parcel_numbers=list(row.target_parcel_numbers or []),
        available_parcel_numbers=list(row.available_parcel_numbers or []),
        entries=entries,
    )


def _tmv_to_row(job: TmvJob) -> TmvJobTable:
    d = job.model_dump(mode="json")
    return TmvJobTable(
        job_id=d["job_id"],
        case_id=d["case_id"],
        status=d["status"],
        started_at=job.started_at,
        last_heartbeat_at=job.last_heartbeat_at,
        address=d.get("address"),
        download_dir=d["download_dir"],
        imported_count=d.get("imported_count", 0),
        skipped_count=d.get("skipped_count", 0),
        error_message=d.get("error_message"),
        import_result_summary=d.get("import_result_summary"),
        user_ready=d.get("user_ready", False),
        status_detail=d.get("status_detail"),
        downloaded_files=d.get("downloaded_files") or [],
    )


def _row_to_tmv(row: TmvJobTable) -> TmvJob:
    return TmvJob(
        job_id=row.job_id,
        case_id=row.case_id,
        status=row.status,
        started_at=row.started_at,
        last_heartbeat_at=row.last_heartbeat_at,
        address=row.address,
        download_dir=row.download_dir,
        imported_count=row.imported_count,
        skipped_count=row.skipped_count,
        error_message=row.error_message,
        import_result_summary=row.import_result_summary,
        user_ready=row.user_ready,
        status_detail=row.status_detail,
        downloaded_files=list(row.downloaded_files or []),
    )


# ---------------------------------------------------------------------------
# Hjælper: hent document_ids for en sag
# ---------------------------------------------------------------------------

def _get_document_ids(session: Session, case_id: str) -> List[str]:
    rows = session.exec(
        select(DocumentTable.document_id)
        .where(DocumentTable.case_id == case_id)
    ).all()
    return list(rows)


def _load_case_row(
    session: Session,
    case_id: str,
    owner_user_id: UUID | None = None,
) -> Optional[CaseTable]:
    stmt = select(CaseTable).where(CaseTable.case_id == case_id)
    if owner_user_id is not None:
        stmt = stmt.where(CaseTable.user_id == owner_user_id)
    return session.exec(stmt).first()


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------

def save_case(session: Session, case: Case) -> None:
    row = _case_to_row(case)
    existing = session.get(CaseTable, case.case_id)
    if existing is not None:
        row.canonical_list = existing.canonical_list
        row.scoring_results = existing.scoring_results
    session.merge(row)
    session.commit()
    logger.debug(f"Saved case {case.case_id}")


def load_case(
    session: Session,
    case_id: str,
    owner_user_id: UUID | None = None,
) -> Optional[Case]:
    row = _load_case_row(session, case_id, owner_user_id=owner_user_id)
    if row is None:
        return None
    doc_ids = _get_document_ids(session, case_id)
    return _row_to_case(row, doc_ids)


def list_cases(session: Session, owner_user_id: UUID | None = None) -> List[Case]:
    stmt = select(CaseTable)
    if owner_user_id is not None:
        stmt = stmt.where(CaseTable.user_id == owner_user_id)
    rows = session.exec(stmt).all()
    doc_rows = session.exec(
        select(DocumentTable.case_id, DocumentTable.document_id)
    ).all()
    ids_by_case: dict[str, List[str]] = {}
    for c_id, d_id in doc_rows:
        ids_by_case.setdefault(c_id, []).append(d_id)
    return [_row_to_case(row, ids_by_case.get(row.case_id, [])) for row in rows]


def delete_case(
    session: Session,
    case_id: str,
    owner_user_id: UUID | None = None,
) -> bool:
    row = _load_case_row(session, case_id, owner_user_id=owner_user_id)
    if row is None:
        return False
    for table in (TmvJobTable, JobTable, ReportTable, ServitutTable, ChunkTable, DocumentTable):
        session.exec(delete(table).where(table.case_id == case_id))
    session.delete(row)
    session.commit()
    case_dir = _case_dir(case_id)
    if case_dir.exists():
        shutil.rmtree(case_dir)
    return True


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def save_job(session: Session, job: Job) -> None:
    session.merge(_job_to_row(job))
    session.commit()


def load_job(
    session: Session,
    case_id: str,
    job_id: str,
    owner_user_id: UUID | None = None,
) -> Optional[Job]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return None
    row = session.get(JobTable, job_id)
    if row is None or row.case_id != case_id:
        return None
    return _row_to_job(row)


def list_jobs(
    session: Session,
    case_id: str,
    owner_user_id: UUID | None = None,
) -> List[Job]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return []
    rows = session.exec(select(JobTable).where(JobTable.case_id == case_id)).all()
    return [_row_to_job(r) for r in rows]


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

def save_document(session: Session, doc: Document) -> None:
    row = _doc_to_row(doc)
    existing = session.get(DocumentTable, doc.document_id)
    if existing is not None:
        row.attest_pipeline_state = existing.attest_pipeline_state
    session.merge(row)
    session.commit()
    logger.debug(f"Saved document {doc.document_id}")


def load_document(
    session: Session,
    case_id: str,
    doc_id: str,
    include_pages: bool = True,
    owner_user_id: UUID | None = None,
) -> Optional[Document]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return None
    row = session.get(DocumentTable, doc_id)
    if row is None or row.case_id != case_id:
        return None
    return _row_to_doc(row, include_pages=include_pages)


def list_documents(
    session: Session,
    case_id: str,
    include_pages: bool = False,
    owner_user_id: UUID | None = None,
) -> List[Document]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return []
    rows = session.exec(
        select(DocumentTable).where(DocumentTable.case_id == case_id)
    ).all()
    return [_row_to_doc(row, include_pages=include_pages) for row in rows]


def delete_document(
    session: Session,
    case_id: str,
    doc_id: str,
    owner_user_id: UUID | None = None,
) -> None:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return
    row = session.get(DocumentTable, doc_id)
    if row is None or row.case_id != case_id:
        return
    session.exec(delete(ChunkTable).where(ChunkTable.document_id == doc_id))
    session.delete(row)
    session.commit()
    get_ocr_path(case_id, doc_id).unlink(missing_ok=True)
    shutil.rmtree(_case_dir(case_id) / "page_images" / doc_id, ignore_errors=True)
    shutil.rmtree(_doc_dir(case_id, doc_id), ignore_errors=True)
    logger.info(f"Deleted document {doc_id} from case {case_id}")


# ---------------------------------------------------------------------------
# OCR-sider
# ---------------------------------------------------------------------------

def save_ocr_pages(session: Session, case_id: str, doc_id: str, pages: list) -> None:
    """Gem sider til JSONB på DocumentTable OG til disk (mtime-friskhedstjek)."""
    pages_data = [
        p.model_dump(mode="json") if hasattr(p, "model_dump") else p for p in pages
    ]
    disk_path = get_ocr_path(case_id, doc_id)
    disk_path.parent.mkdir(parents=True, exist_ok=True)
    save_json(disk_path, pages_data)
    row = session.get(DocumentTable, doc_id)
    if row is not None:
        row.pages = pages_data
        session.add(row)
        session.commit()
    logger.debug(f"Saved {len(pages)} OCR pages for doc {doc_id}")


def load_ocr_pages(
    session: Session,
    case_id: str,
    doc_id: str,
    owner_user_id: UUID | None = None,
) -> list:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return []
    row = session.get(DocumentTable, doc_id)
    if row is None or row.case_id != case_id or not row.pages:
        return []
    return [PageData(**p) for p in row.pages]


# ---------------------------------------------------------------------------
# Attest-pipeline-state
# ---------------------------------------------------------------------------

def save_attest_pipeline_state(
    session: Session,
    case_id: str,
    doc_id: str,
    state: AttestPipelineState | dict | None,
) -> None:
    row = session.get(DocumentTable, doc_id)
    if row is None or row.case_id != case_id:
        return
    if state is None:
        row.attest_pipeline_state = None
    elif isinstance(state, AttestPipelineState):
        row.attest_pipeline_state = state.model_dump(mode="json")
    else:
        row.attest_pipeline_state = state
    session.add(row)
    session.commit()
    logger.debug(f"Saved attest pipeline state for doc {doc_id}")


def load_attest_pipeline_state(
    session: Session,
    case_id: str,
    doc_id: str,
    owner_user_id: UUID | None = None,
) -> Optional[AttestPipelineState]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return None
    row = session.get(DocumentTable, doc_id)
    if row is None or row.case_id != case_id or row.attest_pipeline_state is None:
        return None
    return AttestPipelineState(**row.attest_pipeline_state)


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------

def save_chunks(
    session: Session, case_id: str, doc_id: str, chunks: List[Chunk]
) -> None:
    session.exec(delete(ChunkTable).where(ChunkTable.document_id == doc_id))
    session.add_all([_chunk_to_row(c) for c in chunks])
    session.commit()
    logger.debug(f"Saved {len(chunks)} chunks for doc {doc_id}")


def load_chunks(
    session: Session,
    case_id: str,
    doc_id: str,
    owner_user_id: UUID | None = None,
) -> List[Chunk]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return []
    rows = session.exec(
        select(ChunkTable)
        .where(ChunkTable.document_id == doc_id, ChunkTable.case_id == case_id)
        .order_by(ChunkTable.chunk_index)
    ).all()
    return [_row_to_chunk(r) for r in rows]


def load_all_chunks(
    session: Session,
    case_id: str,
    owner_user_id: UUID | None = None,
) -> List[Chunk]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return []
    rows = session.exec(
        select(ChunkTable)
        .where(ChunkTable.case_id == case_id)
        .order_by(ChunkTable.document_id, ChunkTable.chunk_index)
    ).all()
    return [_row_to_chunk(r) for r in rows]


# ---------------------------------------------------------------------------
# Servitutter
# ---------------------------------------------------------------------------

def save_servitut(session: Session, servitut: Servitut, commit: bool = True) -> None:
    session.merge(_servitut_to_row(servitut))
    if commit:
        session.commit()


def load_servitut(
    session: Session,
    case_id: str,
    easement_id: str,
    owner_user_id: UUID | None = None,
) -> Optional[Servitut]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return None
    row = session.get(ServitutTable, easement_id)
    if row is None or row.case_id != case_id:
        return None
    return _row_to_servitut(row)


def list_servitutter(
    session: Session,
    case_id: str,
    owner_user_id: UUID | None = None,
) -> List[Servitut]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return []
    rows = session.exec(
        select(ServitutTable).where(ServitutTable.case_id == case_id)
    ).all()
    return [_row_to_servitut(r) for r in rows]


def reset_case_extraction_outputs(
    session: Session,
    case_id: str,
    *,
    clear_attest_pipeline: bool = False,
) -> dict[str, int]:
    servitut_count = len(
        session.exec(select(ServitutTable).where(ServitutTable.case_id == case_id)).all()
    )
    report_count = len(
        session.exec(select(ReportTable).where(ReportTable.case_id == case_id)).all()
    )
    declaration_count = len(
        session.exec(
            select(ServituterklaeringTable).where(ServituterklaeringTable.case_id == case_id)
        ).all()
    )

    session.exec(delete(ServitutTable).where(ServitutTable.case_id == case_id))
    session.exec(delete(ReportTable).where(ReportTable.case_id == case_id))
    session.exec(delete(ServituterklaeringTable).where(ServituterklaeringTable.case_id == case_id))

    cleared_attest_states = 0
    if clear_attest_pipeline:
        document_rows = session.exec(
            select(DocumentTable).where(DocumentTable.case_id == case_id)
        ).all()
        for row in document_rows:
            if row.attest_pipeline_state is None:
                continue
            row.attest_pipeline_state = None
            session.add(row)
            cleared_attest_states += 1

    case_row = session.get(CaseTable, case_id)
    if case_row is not None:
        case_row.canonical_list = None
        case_row.scoring_results = None
        session.add(case_row)

    session.commit()
    return {
        "servitutter_deleted": servitut_count,
        "reports_deleted": report_count,
        "declarations_deleted": declaration_count,
        "attest_states_cleared": cleared_attest_states,
    }


# ---------------------------------------------------------------------------
# Canonical liste (JSONB på CaseTable)
# ---------------------------------------------------------------------------

def save_canonical_list(
    session: Session, case_id: str, canonical_list: List[Servitut]
) -> None:
    row = session.get(CaseTable, case_id)
    if row is None:
        return
    row.canonical_list = [s.model_dump(mode="json") for s in canonical_list]
    session.add(row)
    session.commit()
    logger.debug(f"Saved canonical list ({len(canonical_list)}) for case {case_id}")


def load_canonical_list(
    session: Session,
    case_id: str,
    owner_user_id: UUID | None = None,
) -> Optional[List[Servitut]]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return None
    row = session.get(CaseTable, case_id)
    if row is None or row.canonical_list is None:
        return None
    return [Servitut(**s) for s in row.canonical_list]


# ---------------------------------------------------------------------------
# Chunk-scoring
# ---------------------------------------------------------------------------

def save_scoring_results(session: Session, case_id: str, results: list) -> None:
    row = session.get(CaseTable, case_id)
    if row is None:
        return
    row.scoring_results = results
    session.add(row)
    session.commit()
    logger.debug(f"Saved scoring results for case {case_id}")


def load_scoring_results(
    session: Session,
    case_id: str,
    owner_user_id: UUID | None = None,
) -> Optional[list]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return None
    row = session.get(CaseTable, case_id)
    if row is None or row.scoring_results is None:
        return None
    return row.scoring_results


# ---------------------------------------------------------------------------
# Rapporter
# ---------------------------------------------------------------------------

def save_report(session: Session, report: Report) -> None:
    session.merge(_report_to_row(report))
    session.commit()


def load_report(
    session: Session,
    case_id: str,
    report_id: str,
    owner_user_id: UUID | None = None,
) -> Optional[Report]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return None
    row = session.get(ReportTable, report_id)
    if row is None or row.case_id != case_id:
        return None
    return _row_to_report(row)


def list_reports(
    session: Session,
    case_id: str,
    owner_user_id: UUID | None = None,
) -> List[Report]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return []
    rows = session.exec(
        select(ReportTable).where(ReportTable.case_id == case_id)
    ).all()
    return [_row_to_report(r) for r in rows]


# ---------------------------------------------------------------------------
# Servituterklæringer
# ---------------------------------------------------------------------------

def _declaration_to_row(decl: Servituterklaring) -> ServituterklaeringTable:
    d = decl.model_dump(mode="json")
    return ServituterklaeringTable(
        declaration_id=d["declaration_id"],
        case_id=d["case_id"],
        created_at=decl.created_at,
        manually_reviewed=d.get("manually_reviewed", False),
        notes=d.get("notes"),
        target_parcel_numbers=d.get("target_parcel_numbers") or [],
        rows=d.get("rows") or [],
    )


def _row_to_declaration(row: ServituterklaeringTable) -> Servituterklaring:
    rows = [ServituterklaeringRow(**r) for r in (row.rows or [])]
    return Servituterklaring(
        declaration_id=row.declaration_id,
        case_id=row.case_id,
        created_at=row.created_at,
        manually_reviewed=row.manually_reviewed,
        notes=row.notes,
        target_parcel_numbers=list(row.target_parcel_numbers or []),
        rows=rows,
    )


def save_declaration(session: Session, decl: Servituterklaring) -> None:
    session.merge(_declaration_to_row(decl))
    session.commit()


def load_declaration(
    session: Session,
    case_id: str,
    declaration_id: str,
    owner_user_id: UUID | None = None,
) -> Optional[Servituterklaring]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return None
    row = session.get(ServituterklaeringTable, declaration_id)
    if row is None or row.case_id != case_id:
        return None
    return _row_to_declaration(row)


def list_declarations(
    session: Session,
    case_id: str,
    owner_user_id: UUID | None = None,
) -> List[Servituterklaring]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return []
    rows = session.exec(
        select(ServituterklaeringTable)
        .where(ServituterklaeringTable.case_id == case_id)
        .order_by(ServituterklaeringTable.created_at.desc())
    ).all()
    return [_row_to_declaration(r) for r in rows]


# ---------------------------------------------------------------------------
# TMV-jobs
# ---------------------------------------------------------------------------

def save_tmv_job(session: Session, job: TmvJob) -> None:
    session.merge(_tmv_to_row(job))
    session.commit()


def load_tmv_job(
    session: Session,
    case_id: str,
    job_id: str,
    owner_user_id: UUID | None = None,
) -> Optional[TmvJob]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return None
    row = session.get(TmvJobTable, job_id)
    if row is None or row.case_id != case_id:
        return None
    return _row_to_tmv(row)


def list_tmv_jobs(
    session: Session,
    case_id: str,
    owner_user_id: UUID | None = None,
) -> List[TmvJob]:
    if owner_user_id is not None and _load_case_row(
        session, case_id, owner_user_id=owner_user_id
    ) is None:
        return []
    rows = session.exec(
        select(TmvJobTable)
        .where(TmvJobTable.case_id == case_id)
        .order_by(TmvJobTable.started_at.desc())
    ).all()
    return [_row_to_tmv(r) for r in rows]
