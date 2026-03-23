from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlmodel import Field, SQLModel


class Matrikel(SQLModel):
    matrikelnummer: str
    landsejerlav: Optional[str] = None
    areal_m2: Optional[int] = None


class Case(SQLModel):
    case_id: str
    user_id: Optional[UUID] = None
    name: str
    address: Optional[str] = None
    external_ref: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    document_ids: List[str] = Field(default_factory=list)
    matrikler: List[Matrikel] = Field(default_factory=list)
    target_matrikel: Optional[str] = None
    last_extracted_target_matrikel: Optional[str] = None
    status: str = "created"  # created | parsing | extracting | done | error
