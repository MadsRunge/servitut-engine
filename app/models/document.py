from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class PageData(BaseModel):
    page_number: int
    text: str
    extraction_method: str = "pdfplumber"  # pdfplumber | ocr_candidate
    confidence: float = 1.0


class Document(BaseModel):
    document_id: str
    case_id: str
    filename: str
    file_path: str
    document_type: str = "unknown"  # servitut | bbr | ejendomssammendrag | unknown
    created_at: datetime = Field(default_factory=datetime.utcnow)
    page_count: int = 0
    pages: List[PageData] = Field(default_factory=list)
    parse_status: str = "pending"  # pending | parsed | error
