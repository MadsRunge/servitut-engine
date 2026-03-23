from datetime import date, datetime
from typing import List, Optional

from sqlmodel import Field, SQLModel


class ReportEntry(SQLModel):
    nr: int
    date_reference: Optional[str] = None
    raw_text: Optional[str] = None  # Verbatim tekst fra akten
    description: Optional[str] = None
    beneficiary: Optional[str] = None
    disposition: Optional[str] = None
    legal_type: Optional[str] = None
    action: Optional[str] = None
    title: Optional[str] = None
    byggeri_markering: Optional[str] = None  # sort | orange | rød
    relevant_for_project: bool = False
    beneficiary_amt_warning: bool = False
    scope: Optional[str] = None  # "Ja" | "Nej" | "Måske"
    scope_detail: Optional[str] = None  # fx "Vedr. matr.nr. 1o og 1v"
    servitut_id: str


class Report(SQLModel):
    report_id: str
    case_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    edited_at: Optional[datetime] = None
    manually_edited: bool = False
    as_of_date: Optional[date] = None
    target_matrikler: List[str] = Field(default_factory=list)
    available_matrikler: List[str] = Field(default_factory=list)
    servitutter: List[ReportEntry] = Field(default_factory=list)
    notes: Optional[str] = None
    markdown_content: Optional[str] = None
