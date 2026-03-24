"""
SQLModel ORM-tabelklasser.

Disse er *separate* fra Pydantic-DTO'erne i app/models/ som bruges som
API response-typer. storage_service.py konverterer imellem de to lag.

JSONB-kolonner anvendes til:
  - Lister af komplekse objekter (evidence, pages, parcels, report entries …)
  - Lister af strenge (applies_to_parcel_numbers, flags, downloaded_files …)
  - Midlertidigt data på Case (canonical_list, scoring_results)

Chunks har sin egen tabel, fordi de forespørges selvstændigt pr. dokument/sag.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import JSON, Column, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


JSON_VALUE = JSON().with_variant(JSONB(), "postgresql")


class CaseTable(SQLModel, table=True):
    __tablename__ = "cases"

    case_id: str = Field(primary_key=True)
    user_id: Optional[UUID] = Field(default=None, foreign_key="users.id", index=True)
    name: str
    address: Optional[str] = None
    external_ref: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    primary_parcel_number: Optional[str] = None
    last_extracted_primary_parcel_number: Optional[str] = None
    status: str = Field(default="created")
    # JSONB: List[Matrikel] serialiseret som JSON-array
    parcels: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )
    # JSONB: List[Servitut] — canonical liste fra tinglysningsattest (midlertidigt)
    canonical_list: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )
    # JSONB: scorer fra filter-chunks-visning
    scoring_results: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )


class DocumentTable(SQLModel, table=True):
    __tablename__ = "documents"

    document_id: str = Field(primary_key=True)
    case_id: str = Field(index=True, foreign_key="cases.case_id")
    filename: str
    file_path: str
    document_type: str = Field(default="unknown")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    page_count: int = Field(default=0)
    chunk_count: int = Field(default=0)
    ocr_blank_pages: int = Field(default=0)
    ocr_low_conf_pages: int = Field(default=0)
    parse_status: str = Field(default="pending")
    # JSONB: List[PageData] — gemmes også på disk (ocr/{doc_id}_pages.json) til
    # mtime-baseret friskhedstjek i ocr_service
    pages: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )
    # JSONB: attest-segmenter, extraction-status og mellemresultater
    attest_pipeline_state: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )


class ChunkTable(SQLModel, table=True):
    __tablename__ = "chunks"

    chunk_id: str = Field(primary_key=True)
    document_id: str = Field(index=True, foreign_key="documents.document_id")
    case_id: str = Field(index=True, foreign_key="cases.case_id")
    page: int
    text: str = Field(sa_column=Column(Text, nullable=False))
    chunk_index: int
    char_start: int
    char_end: int


class ServitutTable(SQLModel, table=True):
    __tablename__ = "servitutter"

    easement_id: str = Field(primary_key=True)
    case_id: str = Field(index=True, foreign_key="cases.case_id")
    source_document: str
    priority: int = Field(default=0)
    date_reference: Optional[str] = None
    registered_at: Optional[date] = None
    archive_number: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    beneficiary: Optional[str] = None
    disposition_type: Optional[str] = None
    legal_type: Optional[str] = None
    relevance_for_property: Optional[str] = None
    construction_relevance: bool = Field(default=False)
    construction_impact: Optional[str] = None
    action_note: Optional[str] = None
    applies_to_primary_parcel: Optional[bool] = None
    raw_scope_text: Optional[str] = None
    scope_source: Optional[str] = None
    scope_basis: Optional[str] = None
    scope_confidence: Optional[float] = None
    confidence: float = Field(default=0.0)
    confirmed_by_attest: bool = Field(default=True)
    review_status: Optional[str] = None
    review_remarks: Optional[str] = None
    status: str = Field(default="ukendt")
    scope_type: Optional[str] = None
    is_fanout_entry: bool = Field(default=False)
    declaration_block_id: Optional[str] = None
    # JSONB-lister
    applies_to_parcel_numbers: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )
    raw_parcel_references: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )
    # JSONB: List[Evidence]
    evidence: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )
    flags: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )


class JobTable(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(primary_key=True)
    case_id: str = Field(index=True, foreign_key="cases.case_id")
    task_type: str = Field(index=True)
    status: str = Field(index=True)
    result_data: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )


class ReportTable(SQLModel, table=True):
    __tablename__ = "reports"

    report_id: str = Field(primary_key=True)
    case_id: str = Field(index=True, foreign_key="cases.case_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    edited_at: Optional[datetime] = None
    manually_edited: bool = Field(default=False)
    as_of_date: Optional[date] = None
    notes: Optional[str] = None
    markdown_content: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    # JSONB-lister
    target_parcel_numbers: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )
    available_parcel_numbers: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )
    # JSONB: List[ReportEntry]
    entries: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )


class ServituterklaeringTable(SQLModel, table=True):
    __tablename__ = "servituterklaringer"

    declaration_id: str = Field(primary_key=True)
    case_id: str = Field(index=True, foreign_key="cases.case_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    manually_reviewed: bool = Field(default=False)
    notes: Optional[str] = None
    # JSONB: List[str]
    target_parcel_numbers: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )
    # JSONB: List[ServituterklaeringRow]
    rows: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )


class TmvJobTable(SQLModel, table=True):
    __tablename__ = "tmv_jobs"

    job_id: str = Field(primary_key=True)
    case_id: str = Field(index=True, foreign_key="cases.case_id")
    status: str
    started_at: datetime
    last_heartbeat_at: Optional[datetime] = None
    address: Optional[str] = None
    download_dir: str
    imported_count: int = Field(default=0)
    skipped_count: int = Field(default=0)
    error_message: Optional[str] = None
    import_result_summary: Optional[str] = None
    user_ready: bool = Field(default=False)
    status_detail: Optional[str] = None
    # JSONB: list[str]
    downloaded_files: Optional[Any] = Field(
        default=None, sa_column=Column(JSON_VALUE, nullable=True)
    )
