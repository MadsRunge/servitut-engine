from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel
from sqlmodel import Field, SQLModel


class AttestBlockType(str, Enum):
    DECLARATION_START        = "declaration_start"
    DECLARATION_CONTINUATION = "declaration_continuation"
    ANMERKNING_FANOUT        = "anmerkning_fanout"
    ANMERKNING_TEXT          = "anmerkning_text"
    AFLYSNING                = "aflysning"
    UNKNOWN                  = "unknown"


class DeclarationBlock(BaseModel):
    """Semantisk assembly af ét eller flere sammenhængende AttestSegment-objekter.

    Lever kun i pipeline-state JSONB — ikke en selvstændig DB-tabel.
    """
    block_id: str                            # sha256(source_segment_ids joined)[:12]
    case_id: str
    document_id: str
    page_start: int
    page_end: int
    source_segment_ids: List[str]            # provenance → AttestSegment.segment_id
    priority_number: Optional[str] = None
    title: Optional[str] = None
    archive_number: Optional[str] = None
    raw_scope_text: str = ""
    raw_parcel_references: List[str] = []
    has_aflysning: bool = False
    status: str = "ukendt"                   # aktiv | aflyst | ukendt
    fanout_date_refs: List[str] = []         # date_reference-værdier fra ANMERKNING_FANOUT


class AttestSegment(SQLModel):
    segment_id: str
    case_id: str
    document_id: str
    segment_index: int
    segment_type: str = "page_window"
    page_start: int
    page_end: int
    page_numbers: List[int] = Field(default_factory=list)
    chunk_start_index: Optional[int] = None
    chunk_end_index: Optional[int] = None
    text: str
    text_hash: str
    heading: Optional[str] = None
    candidate_date_references: List[str] = Field(default_factory=list)
    candidate_archive_numbers: List[str] = Field(default_factory=list)
    candidate_title: Optional[str] = None
    raw_scope_text: Optional[str] = None
    raw_parcel_references: List[str] = Field(default_factory=list)
    block_type: str = "unknown"              # AttestBlockType streng
    extraction_status: str = "pending"
    extraction_attempts: int = 0
    extraction_error: Optional[str] = None
    extracted_servitutter: List[dict[str, Any]] = Field(default_factory=list)
    last_extracted_at: Optional[datetime] = None


class AttestPipelineState(SQLModel):
    version: int = 1
    case_id: str
    document_id: str
    source_signature: str
    page_count: int = 0
    segment_strategy: str = "page_window_v1"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    segments: List[AttestSegment] = Field(default_factory=list)
    declaration_blocks: List[DeclarationBlock] = Field(default_factory=list)
    unresolved_block_ids: List[str] = Field(default_factory=list)


class AttestDebugSegment(BaseModel):
    segment_id: str
    segment_index: int
    page_start: int
    page_end: int
    page_numbers: List[int]
    heading: Optional[str] = None
    block_type: str
    candidate_date_references: List[str] = []
    candidate_archive_numbers: List[str] = []


class AttestDebugBlock(BaseModel):
    block_id: str
    page_start: int
    page_end: int
    priority_number: Optional[str] = None
    title: Optional[str] = None
    archive_number: Optional[str] = None
    status: str
    has_aflysning: bool
    source_segment_ids: List[str] = []
    raw_parcel_references: List[str] = []
    fanout_date_reference_count: int = 0
    fanout_date_references_sample: List[str] = []


class AttestPipelineDebug(BaseModel):
    case_id: str
    document_id: str
    filename: str
    document_type: str
    version: int
    segment_strategy: str
    page_count: int
    segment_count: int
    declaration_block_count: int
    unresolved_block_ids: List[str] = []
    unresolved_block_count: int = 0
    block_type_counts: dict[str, int] = {}
    segments: List[AttestDebugSegment] = []
    declaration_blocks: List[AttestDebugBlock] = []
