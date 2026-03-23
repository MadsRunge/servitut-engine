from datetime import date
from typing import List, Optional

from sqlmodel import Field, SQLModel


class Evidence(SQLModel):
    chunk_id: str
    document_id: str
    page: int
    text_excerpt: str


class Servitut(SQLModel):
    servitut_id: str
    case_id: str
    source_document: str
    priority: int = 0
    date_reference: Optional[str] = None
    registered_at: Optional[date] = None
    akt_nr: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    beneficiary: Optional[str] = None
    disposition_type: Optional[str] = None  # rådighed | tilstand
    legal_type: Optional[str] = None  # offentlig | privatretlig
    relevance_for_property: Optional[str] = None
    construction_relevance: bool = False
    byggeri_markering: Optional[str] = None  # sort | orange | rød
    action_note: Optional[str] = None
    applies_to_matrikler: List[str] = Field(default_factory=list)
    raw_matrikel_references: List[str] = Field(default_factory=list)
    applies_to_target_matrikel: Optional[bool] = None
    raw_scope_text: Optional[str] = None
    scope_source: Optional[str] = None  # attest | akt | derived
    scope_basis: Optional[str] = None
    scope_confidence: Optional[float] = None
    confidence: float = 0.0
    evidence: List[Evidence] = Field(default_factory=list)
    flags: List[str] = Field(default_factory=list)
    attest_confirmed: bool = True  # False = fundet i akt men ikke i tinglysningsattest
