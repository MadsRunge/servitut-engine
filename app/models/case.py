from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class Case(BaseModel):
    case_id: str
    name: str
    address: Optional[str] = None
    external_ref: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    document_ids: List[str] = Field(default_factory=list)
    status: str = "created"  # created | parsing | extracting | done | error
