from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class ReportEntry(BaseModel):
    nr: int
    date_reference: Optional[str] = None
    description: Optional[str] = None
    beneficiary: Optional[str] = None
    disposition: Optional[str] = None
    legal_type: Optional[str] = None
    action: Optional[str] = None
    relevant_for_project: bool = False
    scope: Optional[str] = None  # "Ja" | "Nej" | "Måske"
    scope_detail: Optional[str] = None  # fx "Vedr. matr.nr. 1o og 1v"
    servitut_id: str


class Report(BaseModel):
    report_id: str
    case_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    target_matrikler: List[str] = Field(default_factory=list)
    available_matrikler: List[str] = Field(default_factory=list)
    servitutter: List[ReportEntry] = Field(default_factory=list)
    notes: Optional[str] = None
    markdown_content: Optional[str] = None
