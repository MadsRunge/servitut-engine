from typing import List, Optional
from pydantic import BaseModel, Field


class Evidence(BaseModel):
    chunk_id: str
    document_id: str
    page: int
    text_excerpt: str


class Servitut(BaseModel):
    servitut_id: str
    case_id: str
    source_document: str
    priority: int = 0
    date_reference: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    beneficiary: Optional[str] = None
    disposition_type: Optional[str] = None  # rådighed | tilstand
    legal_type: Optional[str] = None  # offentlig | privatretlig
    relevance_for_property: Optional[str] = None
    construction_relevance: bool = False
    action_note: Optional[str] = None
    confidence: float = 0.0
    evidence: List[Evidence] = Field(default_factory=list)
    flags: List[str] = Field(default_factory=list)
