from datetime import datetime
from typing import List, Optional

from sqlmodel import Field, SQLModel


class PageData(SQLModel):
    page_number: int
    text: str
    extraction_method: str = "ocrmypdf"
    confidence: float = 0.9


class Document(SQLModel):
    document_id: str
    case_id: str
    filename: str
    file_path: str
    document_type: str = "unknown"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    page_count: int = 0
    chunk_count: int = 0
    ocr_blank_pages: int = 0
    ocr_low_conf_pages: int = 0
    pages: List[PageData] = Field(default_factory=list)
    parse_status: str = "pending"  # pending | processing | ocr_done | error
