from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session

from app.models.document import Document
from app.services import case_service, storage_service
from app.services.document_classifier import classify_document
from app.services.document_service import create_document_from_bytes


@dataclass
class DownloadImportResult:
    imported: list[Document] = field(default_factory=list)
    skipped_existing_duplicates: list[Path] = field(default_factory=list)
    skipped_batch_duplicates: list[Path] = field(default_factory=list)
    skipped_old: list[Path] = field(default_factory=list)
    scanned_pdfs: int = 0


def import_downloaded_pdfs(
    session: Session,
    case_id: str,
    source_dir: str | Path,
    *,
    modified_after: datetime | None = None,
) -> DownloadImportResult:
    if not case_service.get_case(session, case_id):
        raise ValueError(f"Case not found: {case_id}")

    source_path = Path(source_dir).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if not source_path.is_dir():
        raise NotADirectoryError(source_path)

    existing_hashes = _load_existing_hashes(session, case_id)
    imported_hashes: set[str] = set()
    result = DownloadImportResult()

    for pdf_path in sorted(source_path.iterdir()):
        if pdf_path.suffix.lower() != ".pdf" or not pdf_path.is_file():
            continue

        result.scanned_pdfs += 1
        if modified_after and _modified_at(pdf_path) <= _as_utc(modified_after):
            result.skipped_old.append(pdf_path)
            continue

        pdf_hash = _hash_file(pdf_path)
        if pdf_hash in existing_hashes:
            result.skipped_existing_duplicates.append(pdf_path)
            continue
        if pdf_hash in imported_hashes:
            result.skipped_batch_duplicates.append(pdf_path)
            continue

        doc = create_document_from_bytes(
            session=session,
            case_id=case_id,
            filename=pdf_path.name,
            file_bytes=pdf_path.read_bytes(),
            document_type=classify_document(pdf_path.name),
        )
        result.imported.append(doc)
        imported_hashes.add(pdf_hash)

    return result


def _load_existing_hashes(session: Session, case_id: str) -> set[str]:
    hashes: set[str] = set()
    for doc in storage_service.list_documents(session, case_id):
        pdf_path = storage_service.get_document_pdf_path(case_id, doc.document_id)
        if pdf_path.exists():
            hashes.add(_hash_file(pdf_path))
    return hashes


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _modified_at(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
