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

from sqlalchemy import delete
from sqlmodel import Session, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import (
    CaseTable,
    ChunkTable,
    DocumentTable,
    ReportTable,
    ServitutTable,
    TmvJobTable,
)
from app.models.case import Case, Matrikel
from app.models.chunk import Chunk
from app.models.document import Document, PageData
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
        target_matrikel=d.get("target_matrikel"),
        last_extracted_target_matrikel=d.get("last_extracted_target_matrikel"),
        status=d.get("status", "created"),
        matrikler=d.get("matrikler") or [],
    )


def _row_to_case(row: CaseTable, document_ids: List[str]) -> Case:
    matrikler = [Matrikel(**m) for m in (row.matrikler or [])]
    return Case(
        case_id=row.case_id,
        user_id=row.user_id,
        name=row.name,
        address=row.address,
        external_ref=row.external_ref,
        created_at=row.created_at,
        target_matrikel=row.target_matrikel,
        last_extracted_target_matrikel=row.last_extracted_target_matrikel,
        status=row.status,
        matrikler=matrikler,
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
        servitut_id=d["servitut_id"],
        case_id=d["case_id"],
        source_document=d["source_document"],
        priority=d.get("priority", 0),
        date_reference=d.get("date_reference"),
        registered_at=srv.registered_at,
        akt_nr=d.get("akt_nr"),
        title=d.get("title"),
        summary=d.get("summary"),
        beneficiary=d.get("beneficiary"),
        disposition_type=d.get("disposition_type"),
        legal_type=d.get("legal_type"),
        relevance_for_property=d.get("relevance_for_property"),
        construction_relevance=d.get("construction_relevance", False),
        byggeri_markering=d.get("byggeri_markering"),
        action_note=d.get("action_note"),
        applies_to_target_matrikel=d.get("applies_to_target_matrikel"),
        raw_scope_text=d.get("raw_scope_text"),
        scope_source=d.get("scope_source"),
        scope_basis=d.get("scope_basis"),
        scope_confidence=d.get("scope_confidence"),
        confidence=d.get("confidence", 0.0),
        attest_confirmed=d.get("attest_confirmed", True),
        applies_to_matrikler=d.get("applies_to_matrikler") or [],
        raw_matrikel_references=d.get("raw_matrikel_references") or [],
        evidence=d.get("evidence") or [],
        flags=d.get("flags") or [],
    )


def _row_to_servitut(row: ServitutTable) -> Servitut:
    evidence = [Evidence(**e) for e in (row.evidence or [])]
    return Servitut(
        servitut_id=row.servitut_id,
        case_id=row.case_id,
        source_document=row.source_document,
        priority=row.priority,
        date_reference=row.date_reference,
        registered_at=row.registered_at,
        akt_nr=row.akt_nr,
        title=row.title,
        summary=row.summary,
        beneficiary=row.beneficiary,
        disposition_type=row.disposition_type,
        legal_type=row.legal_type,
        relevance_for_property=row.relevance_for_property,
        construction_relevance=row.construction_relevance,
        byggeri_markering=row.byggeri_markering,
        action_note=row.action_note,
        applies_to_target_matrikel=row.applies_to_target_matrikel,
        raw_scope_text=row.raw_scope_text,
        scope_source=row.scope_source,
        scope_basis=row.scope_basis,
        scope_confidence=row.scope_confidence,
        confidence=row.confidence,
        attest_confirmed=row.attest_confirmed,
        applies_to_matrikler=list(row.applies_to_matrikler or []),
        raw_matrikel_references=list(row.raw_matrikel_references or []),
        evidence=evidence,
        flags=list(row.flags or []),
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
        target_matrikler=d.get("target_matrikler") or [],
        available_matrikler=d.get("available_matrikler") or [],
        servitutter=d.get("servitutter") or [],
    )


def _row_to_report(row: ReportTable) -> Report:
    entries = [ReportEntry(**e) for e in (row.servitutter or [])]
    return Report(
        report_id=row.report_id,
        case_id=row.case_id,
        created_at=row.created_at,
        edited_at=row.edited_at,
        manually_edited=row.manually_edited,
        as_of_date=row.as_of_date,
        notes=row.notes,
        markdown_content=row.markdown_content,
        target_matrikler=list(row.target_matrikler or []),
        available_matrikler=list(row.available_matrikler or []),
        servitutter=entries,
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


def load_case(session: Session, case_id: str) -> Optional[Case]:
    row = session.get(CaseTable, case_id)
    if row is None:
        return None
    doc_ids = _get_document_ids(session, case_id)
    return _row_to_case(row, doc_ids)


def list_cases(session: Session) -> List[Case]:
    rows = session.exec(select(CaseTable)).all()
    doc_rows = session.exec(
        select(DocumentTable.case_id, DocumentTable.document_id)
    ).all()
    ids_by_case: dict[str, List[str]] = {}
    for c_id, d_id in doc_rows:
        ids_by_case.setdefault(c_id, []).append(d_id)
    return [_row_to_case(row, ids_by_case.get(row.case_id, [])) for row in rows]


def delete_case(session: Session, case_id: str) -> bool:
    row = session.get(CaseTable, case_id)
    if row is None:
        return False
    for table in (TmvJobTable, ReportTable, ServitutTable, ChunkTable, DocumentTable):
        session.exec(delete(table).where(table.case_id == case_id))
    session.delete(row)
    session.commit()
    case_dir = _case_dir(case_id)
    if case_dir.exists():
        shutil.rmtree(case_dir)
    return True


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

def save_document(session: Session, doc: Document) -> None:
    row = _doc_to_row(doc)
    session.merge(row)
    session.commit()
    logger.debug(f"Saved document {doc.document_id}")


def load_document(
    session: Session,
    case_id: str,
    doc_id: str,
    include_pages: bool = True,
) -> Optional[Document]:
    row = session.get(DocumentTable, doc_id)
    if row is None or row.case_id != case_id:
        return None
    return _row_to_doc(row, include_pages=include_pages)


def list_documents(
    session: Session,
    case_id: str,
    include_pages: bool = False,
) -> List[Document]:
    rows = session.exec(
        select(DocumentTable).where(DocumentTable.case_id == case_id)
    ).all()
    return [_row_to_doc(row, include_pages=include_pages) for row in rows]


def delete_document(session: Session, case_id: str, doc_id: str) -> None:
    session.exec(delete(ChunkTable).where(ChunkTable.document_id == doc_id))
    row = session.get(DocumentTable, doc_id)
    if row is not None:
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


def load_ocr_pages(session: Session, case_id: str, doc_id: str) -> list:
    row = session.get(DocumentTable, doc_id)
    if row is None or not row.pages:
        return []
    return [PageData(**p) for p in row.pages]


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


def load_chunks(session: Session, case_id: str, doc_id: str) -> List[Chunk]:
    rows = session.exec(
        select(ChunkTable)
        .where(ChunkTable.document_id == doc_id, ChunkTable.case_id == case_id)
        .order_by(ChunkTable.chunk_index)
    ).all()
    return [_row_to_chunk(r) for r in rows]


def load_all_chunks(session: Session, case_id: str) -> List[Chunk]:
    rows = session.exec(
        select(ChunkTable)
        .where(ChunkTable.case_id == case_id)
        .order_by(ChunkTable.document_id, ChunkTable.chunk_index)
    ).all()
    return [_row_to_chunk(r) for r in rows]


# ---------------------------------------------------------------------------
# Servitutter
# ---------------------------------------------------------------------------

def save_servitut(session: Session, servitut: Servitut) -> None:
    session.merge(_servitut_to_row(servitut))
    session.commit()


def load_servitut(
    session: Session, case_id: str, servitut_id: str
) -> Optional[Servitut]:
    row = session.get(ServitutTable, servitut_id)
    if row is None or row.case_id != case_id:
        return None
    return _row_to_servitut(row)


def list_servitutter(session: Session, case_id: str) -> List[Servitut]:
    rows = session.exec(
        select(ServitutTable).where(ServitutTable.case_id == case_id)
    ).all()
    return [_row_to_servitut(r) for r in rows]


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
    session: Session, case_id: str
) -> Optional[List[Servitut]]:
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


def load_scoring_results(session: Session, case_id: str) -> Optional[list]:
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
    session: Session, case_id: str, report_id: str
) -> Optional[Report]:
    row = session.get(ReportTable, report_id)
    if row is None or row.case_id != case_id:
        return None
    return _row_to_report(row)


def list_reports(session: Session, case_id: str) -> List[Report]:
    rows = session.exec(
        select(ReportTable).where(ReportTable.case_id == case_id)
    ).all()
    return [_row_to_report(r) for r in rows]


# ---------------------------------------------------------------------------
# TMV-jobs
# ---------------------------------------------------------------------------

def save_tmv_job(session: Session, job: TmvJob) -> None:
    session.merge(_tmv_to_row(job))
    session.commit()


def load_tmv_job(
    session: Session, case_id: str, job_id: str
) -> Optional[TmvJob]:
    row = session.get(TmvJobTable, job_id)
    if row is None or row.case_id != case_id:
        return None
    return _row_to_tmv(row)


def list_tmv_jobs(session: Session, case_id: str) -> List[TmvJob]:
    rows = session.exec(
        select(TmvJobTable)
        .where(TmvJobTable.case_id == case_id)
        .order_by(TmvJobTable.started_at.desc())
    ).all()
    return [_row_to_tmv(r) for r in rows]
