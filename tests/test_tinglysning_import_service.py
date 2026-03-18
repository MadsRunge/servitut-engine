from datetime import datetime, timedelta, timezone
import os

import pytest

from app.core.config import settings
from app.services import storage_service
from app.services.case_service import create_case
from app.services.document_service import create_document_from_bytes
from app.services.tinglysning_import_service import import_downloaded_pdfs


def test_import_downloaded_pdfs_filters_old_files_and_deduplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    (tmp_path / "cases").mkdir()

    case = create_case("Tinglysning import")
    create_document_from_bytes(
        case_id=case.case_id,
        filename="eksisterende.pdf",
        file_bytes=b"same-bytes",
        document_type="akt",
    )

    download_dir = tmp_path / "downloads"
    download_dir.mkdir()

    cutoff = datetime.now(timezone.utc)
    old_time = cutoff - timedelta(minutes=5)
    new_time = cutoff + timedelta(minutes=5)

    _write_pdf(download_dir / "Min Tinglysningsattest.pdf", b"attest-bytes", new_time)
    _write_pdf(download_dir / "dupe-existing.pdf", b"same-bytes", new_time)
    _write_pdf(download_dir / "akt-a.pdf", b"batch-dupe", new_time)
    _write_pdf(download_dir / "akt-b.pdf", b"batch-dupe", new_time)
    _write_pdf(download_dir / "old.pdf", b"old-bytes", old_time)
    (download_dir / "note.txt").write_text("ignore me")

    result = import_downloaded_pdfs(case.case_id, download_dir, modified_after=cutoff)

    imported_names = sorted(doc.filename for doc in result.imported)
    assert imported_names == ["Min Tinglysningsattest.pdf", "akt-a.pdf"]
    assert result.imported[0].document_type == "tinglysningsattest"
    assert len(result.skipped_existing_duplicates) == 1
    assert len(result.skipped_batch_duplicates) == 1
    assert len(result.skipped_old) == 1
    assert result.scanned_pdfs == 5

    stored_docs = storage_service.list_documents(case.case_id)
    assert len(stored_docs) == 3


def test_import_downloaded_pdfs_requires_existing_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    (tmp_path / "cases").mkdir()

    case = create_case("Tinglysning import")

    with pytest.raises(FileNotFoundError):
        import_downloaded_pdfs(case.case_id, tmp_path / "missing")


def _write_pdf(path, content: bytes, modified_at: datetime) -> None:
    path.write_bytes(content)
    ts = modified_at.timestamp()
    path.touch()
    os.utime(path, (ts, ts))
