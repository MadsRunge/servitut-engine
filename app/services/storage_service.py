from pathlib import Path
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.models.case import Case
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.report import Report
from app.models.servitut import Servitut
from app.utils.files import json_exists, load_json, save_json

logger = get_logger(__name__)


def _case_dir(case_id: str) -> Path:
    return settings.cases_path / case_id


def _doc_dir(case_id: str, doc_id: str) -> Path:
    return _case_dir(case_id) / "documents" / doc_id


# --- Case ---

def save_case(case: Case) -> None:
    path = _case_dir(case.case_id) / "case.json"
    save_json(path, case.model_dump())
    logger.debug(f"Saved case {case.case_id}")


def load_case(case_id: str) -> Optional[Case]:
    path = _case_dir(case_id) / "case.json"
    if not json_exists(path):
        return None
    return Case(**load_json(path))


def list_cases() -> List[Case]:
    cases_root = settings.cases_path
    if not cases_root.exists():
        return []
    cases = []
    for case_dir in sorted(cases_root.iterdir()):
        path = case_dir / "case.json"
        if json_exists(path):
            try:
                cases.append(Case(**load_json(path)))
            except Exception as e:
                logger.warning(f"Could not load case from {path}: {e}")
    return cases


def delete_case(case_id: str) -> bool:
    import shutil
    case_dir = _case_dir(case_id)
    if case_dir.exists():
        shutil.rmtree(case_dir)
        return True
    return False


# --- Document ---

def save_document(doc: Document) -> None:
    path = _doc_dir(doc.case_id, doc.document_id) / "metadata.json"
    # Save pages separately for readability
    pages_path = _doc_dir(doc.case_id, doc.document_id) / "pages.json"
    doc_dict = doc.model_dump()
    pages = doc_dict.pop("pages")
    save_json(path, doc_dict)
    save_json(pages_path, pages)
    logger.debug(f"Saved document {doc.document_id}")


def load_document(case_id: str, doc_id: str) -> Optional[Document]:
    meta_path = _doc_dir(case_id, doc_id) / "metadata.json"
    pages_path = _doc_dir(case_id, doc_id) / "pages.json"
    if not json_exists(meta_path):
        return None
    data = load_json(meta_path)
    if json_exists(pages_path):
        data["pages"] = load_json(pages_path)
    else:
        data["pages"] = []
    return Document(**data)


def list_documents(case_id: str) -> List[Document]:
    docs_dir = _case_dir(case_id) / "documents"
    if not docs_dir.exists():
        return []
    docs = []
    for doc_dir in sorted(docs_dir.iterdir()):
        meta_path = doc_dir / "metadata.json"
        if json_exists(meta_path):
            try:
                data = load_json(meta_path)
                pages_path = doc_dir / "pages.json"
                data["pages"] = load_json(pages_path) if json_exists(pages_path) else []
                docs.append(Document(**data))
            except Exception as e:
                logger.warning(f"Could not load document from {doc_dir}: {e}")
    return docs


def get_document_pdf_path(case_id: str, doc_id: str) -> Path:
    return _doc_dir(case_id, doc_id) / "original.pdf"


# --- Chunks ---

def save_chunks(case_id: str, doc_id: str, chunks: List[Chunk]) -> None:
    path = _doc_dir(case_id, doc_id) / "chunks.json"
    save_json(path, [c.model_dump() for c in chunks])
    logger.debug(f"Saved {len(chunks)} chunks for doc {doc_id}")


def load_chunks(case_id: str, doc_id: str) -> List[Chunk]:
    path = _doc_dir(case_id, doc_id) / "chunks.json"
    if not json_exists(path):
        return []
    return [Chunk(**c) for c in load_json(path)]


def load_all_chunks(case_id: str) -> List[Chunk]:
    case = load_case(case_id)
    if not case:
        return []
    all_chunks = []
    for doc_id in case.document_ids:
        all_chunks.extend(load_chunks(case_id, doc_id))
    return all_chunks


# --- Servitutter ---

def save_servitut(servitut: Servitut) -> None:
    path = _case_dir(servitut.case_id) / "servitutter" / f"{servitut.servitut_id}.json"
    save_json(path, servitut.model_dump())


def load_servitut(case_id: str, servitut_id: str) -> Optional[Servitut]:
    path = _case_dir(case_id) / "servitutter" / f"{servitut_id}.json"
    if not json_exists(path):
        return None
    return Servitut(**load_json(path))


def list_servitutter(case_id: str) -> List[Servitut]:
    srv_dir = _case_dir(case_id) / "servitutter"
    if not srv_dir.exists():
        return []
    result = []
    for f in sorted(srv_dir.glob("*.json")):
        try:
            result.append(Servitut(**load_json(f)))
        except Exception as e:
            logger.warning(f"Could not load servitut {f}: {e}")
    return result


# --- Reports ---

def save_report(report: Report) -> None:
    path = _case_dir(report.case_id) / "reports" / f"{report.report_id}.json"
    save_json(path, report.model_dump())


def load_report(case_id: str, report_id: str) -> Optional[Report]:
    path = _case_dir(case_id) / "reports" / f"{report_id}.json"
    if not json_exists(path):
        return None
    return Report(**load_json(path))


def list_reports(case_id: str) -> List[Report]:
    reports_dir = _case_dir(case_id) / "reports"
    if not reports_dir.exists():
        return []
    result = []
    for f in sorted(reports_dir.glob("*.json")):
        try:
            result.append(Report(**load_json(f)))
        except Exception as e:
            logger.warning(f"Could not load report {f}: {e}")
    return result
