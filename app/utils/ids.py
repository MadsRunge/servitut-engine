import hashlib
import uuid


def generate_case_id() -> str:
    return "case-" + uuid.uuid4().hex[:8]


def generate_doc_id() -> str:
    return "doc-" + uuid.uuid4().hex[:8]


def generate_servitut_id() -> str:
    return "srv-" + uuid.uuid4().hex[:8]


def generate_report_id() -> str:
    return "rep-" + uuid.uuid4().hex[:8]


def generate_job_id() -> str:
    return "job-" + uuid.uuid4().hex[:8]


def generate_declaration_id() -> str:
    return "dec-" + uuid.uuid4().hex[:8]


def generate_chunk_id(doc_id: str, page: int, chunk_index: int) -> str:
    raw = f"{doc_id}:{page}:{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]
