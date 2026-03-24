from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class AttestSegment(BaseModel):
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
    raw_matrikel_references: List[str] = Field(default_factory=list)
    extraction_status: str = "pending"
    extraction_attempts: int = 0
    extraction_error: Optional[str] = None
    extraction_max_tokens: Optional[int] = None
    extracted_servitutter: List[dict[str, Any]] = Field(default_factory=list)
    last_extracted_at: Optional[datetime] = None


class AttestPipelineState(BaseModel):
    version: int = 1
    case_id: str
    document_id: str
    source_signature: str
    page_count: int = 0
    segment_strategy: str = "page_window_v1"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    segments: List[AttestSegment] = Field(default_factory=list)
