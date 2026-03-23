"""
Pydantic DTO-modeller for Servituterklæring.

En erklæring er et deterministisk snapshot af alle servitutter for en sag
med reviewstatus og faglige bemærkninger pr. servitut.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class ReviewStatus(str, Enum):
    klar = "klar"
    kun_i_akt = "kun_i_akt"
    historisk_matrikel = "historisk_matrikel"
    mangler_kilde = "mangler_kilde"
    kraever_kontrol = "kraever_kontrol"


class ServituterklaeringRow(BaseModel):
    sequence_number: int
    easement_id: str
    priority: int = 0
    date_reference: Optional[str] = None
    title: Optional[str] = None
    archive_number: Optional[str] = None
    beneficiary: Optional[str] = None
    remarks: str = ""
    applies_to_parcel_numbers: List[str] = []
    review_status: ReviewStatus = ReviewStatus.klar
    confirmed_by_attest: bool = True
    confidence: float = 0.0
    scope: Optional[str] = None  # "Ja" | "Måske" | "Nej"


class Servituterklaring(BaseModel):
    declaration_id: str
    case_id: str
    created_at: datetime
    target_parcel_numbers: List[str] = []
    rows: List[ServituterklaeringRow] = []
    notes: Optional[str] = None
    manually_reviewed: bool = False


class DeclarationRowPatch(BaseModel):
    easement_id: str
    review_status: Optional[ReviewStatus] = None
    remarks: Optional[str] = None


class DeclarationPatch(BaseModel):
    rows: Optional[List[DeclarationRowPatch]] = None
    notes: Optional[str] = None
