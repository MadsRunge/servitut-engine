from __future__ import annotations

from typing import Any, Literal

from sqlmodel import SQLModel


JobTaskType = Literal["ocr", "extraction"]
JobStatus = Literal["pending", "processing", "completed", "failed"]


class Job(SQLModel):
    id: str
    case_id: str
    task_type: JobTaskType
    status: JobStatus
    result_data: Any | None = None
