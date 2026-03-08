from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class Matrikel(BaseModel):
    matrikelnummer: str
    landsejerlav: Optional[str] = None
    areal_m2: Optional[int] = None


class Case(BaseModel):
    case_id: str
    name: str
    address: Optional[str] = None
    external_ref: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    document_ids: List[str] = Field(default_factory=list)
    matrikler: List[Matrikel] = Field(default_factory=list)
    target_matrikel: Optional[str] = None
    last_extracted_target_matrikel: Optional[str] = None
    status: str = "created"  # created | parsing | extracting | done | error
