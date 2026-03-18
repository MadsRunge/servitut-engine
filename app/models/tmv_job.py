from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class TmvJob(BaseModel):
    job_id: str
    case_id: str
    status: str  # se gyldige statusser nedenfor
    started_at: datetime
    last_heartbeat_at: Optional[datetime] = None
    address: Optional[str] = None
    download_dir: str
    downloaded_files: list[str] = Field(default_factory=list)
    imported_count: int = 0
    skipped_count: int = 0
    error_message: Optional[str] = None
    import_result_summary: Optional[str] = None
    user_ready: bool = False  # sættes True af Streamlit når brugeren er klar til download


# Gyldige statusser (rækkefølge afspejler flowet):
# pending → browser_started → waiting_for_login
# → listing_documents → downloading_documents → importing_documents → completed
# Terminaltilstande: completed | failed | cancelled

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {
    "pending",
    "browser_started",
    "waiting_for_login",
    "listing_documents",
    "downloading_documents",
    "importing_documents",
}
