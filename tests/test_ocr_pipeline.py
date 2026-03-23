"""
Tests for OCR pipeline: process_document → List[PageData]

OCRmyPDF og pdfplumber mockes — ingen rigtige PDF-filer kræves.
"""
import json
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.db.database import create_tables, get_session_ctx, reset_engine_cache
from app.models.chunk import Chunk
from app.models.document import Document, PageData
from app.services import storage_service
from app.services.ocr_service import (
    _estimate_confidence,
    _try_extract_text_direct,
    extract_pages_from_ocr_pdf,
    process_document,
    run_document_pipeline,
    summarize_pages,
)


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    (tmp_path / "cases").mkdir()
    reset_engine_cache()
    create_tables()
    yield tmp_path
    reset_engine_cache()


# --- _estimate_confidence ---

def test_confidence_empty_text():
    assert _estimate_confidence("") == 0.0


def test_confidence_normal_text():
    text = "Servitutten vedrører vejret til naboejendommen matr. nr. 5a."
    conf = _estimate_confidence(text)
    assert conf > 0.6


def test_confidence_noise():
    # Primært symboler/støj
    conf = _estimate_confidence("!@#$%^&*()[]{}|\\<>,./?;:'\"~`")
    assert conf < 0.3


def test_confidence_capped_at_one():
    conf = _estimate_confidence("abcdefghijklmnopqrstuvwxyz" * 10)
    assert conf <= 1.0


# --- extract_pages_from_ocr_pdf ---

def test_extract_pages_from_ocr_pdf(tmp_path):
    ocr_pdf = tmp_path / "ocr.pdf"
    ocr_pdf.write_bytes(b"%PDF-1.4 fake")

    mock_page_1 = MagicMock()
    mock_page_1.extract_text.return_value = "Servitut vedrørende vejret til naboejendommen."
    mock_page_2 = MagicMock()
    mock_page_2.extract_text.return_value = ""

    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page_1, mock_page_2]

    with patch("pdfplumber.open", return_value=mock_pdf):
        pages = extract_pages_from_ocr_pdf(ocr_pdf)

    assert len(pages) == 2
    assert pages[0].page_number == 1
    assert "vejret" in pages[0].text.lower()
    assert pages[0].extraction_method == "ocrmypdf"
    assert pages[0].confidence > 0.0
    assert pages[1].page_number == 2
    assert pages[1].text == ""
    assert pages[1].confidence == 0.0


# --- process_document ---

def test_process_document_returns_pages(tmp_path):
    pdf_path = tmp_path / "original.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    ocr_pdf_path = tmp_path / "ocr.pdf"
    settings.OCR_BATCH_SIZE = 0

    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Deklaration om byggelinier tinglyst 1971."

    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]

    def fake_ocr(input_file, output_file, **kwargs):
        shutil.copy(str(input_file), str(output_file))

    with patch("ocrmypdf.ocr", fake_ocr):
        with patch("pdfplumber.open", return_value=mock_pdf):
            pages = process_document(pdf_path, "doc-test", "case-test", ocr_pdf_path)

    assert len(pages) == 1
    assert pages[0].extraction_method == "ocrmypdf"
    assert "deklaration" in pages[0].text.lower()
    assert ocr_pdf_path.exists()


def test_process_document_handles_prior_ocr(tmp_path):
    """PriorOcrFoundError skal resultere i at original kopieres til ocr.pdf."""
    import ocrmypdf.exceptions

    pdf_path = tmp_path / "original.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    ocr_pdf_path = tmp_path / "ocr.pdf"
    settings.OCR_BATCH_SIZE = 0

    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Eksisterende tekstlag."

    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]

    def raise_prior_ocr(*args, **kwargs):
        raise ocrmypdf.exceptions.PriorOcrFoundError()

    with patch("ocrmypdf.ocr", raise_prior_ocr):
        with patch("pdfplumber.open", return_value=mock_pdf):
            pages = process_document(pdf_path, "doc-x", "case-x", ocr_pdf_path)

    assert ocr_pdf_path.exists()
    assert len(pages) == 1


def test_run_document_pipeline_builds_missing_artifacts(temp_storage):
    case_id = "case-test"
    doc_id = "doc-test"
    pdf_path = storage_service.get_document_pdf_path(case_id, doc_id)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    doc = Document(
        document_id=doc_id,
        case_id=case_id,
        filename="akt.pdf",
        file_path=str(pdf_path),
        document_type="akt",
    )

    pages = [PageData(page_number=1, text="Servitut om vejret", confidence=0.9)]
    chunks = [
        Chunk(
            chunk_id="chunk-1",
            document_id=doc_id,
            case_id=case_id,
            page=1,
            text="Servitut om vejret",
            chunk_index=0,
            char_start=0,
            char_end=18,
        )
    ]

    with get_session_ctx() as session:
        storage_service.save_document(session, doc)
        with patch("app.services.ocr_service.run_ocrmypdf") as mock_run_ocr:
            with patch("app.services.ocr_service.extract_pages_from_ocr_pdf", return_value=pages):
                with patch("app.services.ocr_service.chunk_pages", return_value=chunks):
                    result = run_document_pipeline(session, case_id, doc)

    mock_run_ocr.assert_called_once()
    assert result.reused_ocr_pdf is False
    assert result.reused_pages is False
    assert result.reused_chunks is False
    assert doc.parse_status == "ocr_done"
    assert doc.page_count == 1
    assert doc.chunk_count == 1
    with get_session_ctx() as session:
        assert storage_service.load_ocr_pages(session, case_id, doc_id)[0].text == "Servitut om vejret"
        assert storage_service.load_chunks(session, case_id, doc_id)[0].text == "Servitut om vejret"


def test_run_document_pipeline_reuses_fresh_artifacts(temp_storage):
    case_id = "case-test"
    doc_id = "doc-test"
    pdf_path = storage_service.get_document_pdf_path(case_id, doc_id)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    doc = Document(
        document_id=doc_id,
        case_id=case_id,
        filename="akt.pdf",
        file_path=str(pdf_path),
        document_type="akt",
    )

    pages = [PageData(page_number=1, text="Eksisterende OCR", confidence=0.95)]
    chunks = [
        Chunk(
            chunk_id="chunk-1",
            document_id=doc_id,
            case_id=case_id,
            page=1,
            text="Eksisterende OCR",
            chunk_index=0,
            char_start=0,
            char_end=16,
        )
    ]

    ocr_pdf_path = storage_service.get_ocr_pdf_path(case_id, doc_id)
    ocr_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    ocr_pdf_path.write_bytes(b"%PDF-1.4 ocr")
    with get_session_ctx() as session:
        storage_service.save_document(session, doc)
        storage_service.save_ocr_pages(session, case_id, doc_id, pages)
        storage_service.save_chunks(session, case_id, doc_id, chunks)

    original_ts = 1_000
    ocr_ts = 1_100
    pages_ts = 1_200
    os.utime(pdf_path, (original_ts, original_ts))
    os.utime(ocr_pdf_path, (ocr_ts, ocr_ts))
    os.utime(storage_service.get_ocr_path(case_id, doc_id), (pages_ts, pages_ts))

    with patch("app.services.ocr_service.run_ocrmypdf", side_effect=AssertionError("ocrmypdf should not run")):
        with patch(
            "app.services.ocr_service.extract_pages_from_ocr_pdf",
            side_effect=AssertionError("page extraction should not run"),
        ):
            with patch(
                "app.services.ocr_service.chunk_pages",
                side_effect=AssertionError("chunking should not run"),
            ):
                with get_session_ctx() as session:
                    result = run_document_pipeline(session, case_id, doc)

    assert result.reused_ocr_pdf is True
    assert result.reused_pages is True
    assert result.reused_chunks is True
    assert doc.parse_status == "ocr_done"
    assert doc.page_count == 1
    assert doc.chunk_count == 1
    assert doc.pages[0].text == "Eksisterende OCR"


def test_summarize_pages_counts_blank_low_and_ok():
    pages = [
        PageData(page_number=1, text="Læsbar tekst", confidence=0.9),
        PageData(page_number=2, text="Lidt støj", confidence=0.2),
        PageData(page_number=3, text="", confidence=0.0),
    ]

    blank, low, ok = summarize_pages(pages)

    assert (blank, low, ok) == (1, 1, 1)


# --- Regressions: ingen vision-referencer i OCR-service ---

def test_no_vision_references_in_ocr_service():
    source = Path("app/services/ocr_service.py").read_text(encoding="utf-8")
    assert "claude" not in source.lower(), "claude-reference fundet i ocr_service.py"
    assert "vision" not in source.lower(), "vision-reference fundet i ocr_service.py"
    assert "base64" not in source.lower(), "base64 (vision-legacy) fundet i ocr_service.py"


def test_extraction_method_is_ocrmypdf():
    page = PageData(page_number=1, text="test")
    assert page.extraction_method == "ocrmypdf"


# --- _try_extract_text_direct ---

def _make_pdfplumber_mock(pages_text: list[str]):
    """Hjælper: returnerer en pdfplumber.open context-manager-mock."""
    mock_pages = []
    for text in pages_text:
        pg = MagicMock()
        pg.extract_text.return_value = text
        mock_pages.append(pg)
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = mock_pages
    return mock_pdf


def test_try_extract_text_direct_returns_pages_when_coverage_sufficient(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"fake")

    good_text = "Deklaration om vejret til naboejendommen matr. nr. 5a tinglyst 1971."
    pages_text = [good_text] * 8 + [""] * 2  # 80% coverage → over tærskel

    with patch("pdfplumber.open", return_value=_make_pdfplumber_mock(pages_text)):
        result = _try_extract_text_direct(pdf_path)

    assert result is not None
    assert len(result) == 10
    assert result[0].extraction_method == "pdfplumber_direct"
    assert result[0].confidence > 0.0


def test_try_extract_text_direct_returns_none_when_coverage_insufficient(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"fake")

    good_text = "Deklaration om vejret til naboejendommen matr. nr. 5a."
    pages_text = [good_text] * 3 + [""] * 7  # 30% coverage → under tærskel

    with patch("pdfplumber.open", return_value=_make_pdfplumber_mock(pages_text)):
        result = _try_extract_text_direct(pdf_path)

    assert result is None


def test_try_extract_text_direct_returns_none_on_pdfplumber_error(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"not a pdf")

    with patch("pdfplumber.open", side_effect=Exception("corrupt PDF")):
        result = _try_extract_text_direct(pdf_path)

    assert result is None


def test_run_document_pipeline_uses_direct_path_when_available(temp_storage):
    """Hvis direkte tekstudtræk lykkes, springes ocrmypdf over."""
    case_id = "case-test"
    doc_id = "doc-direct"
    pdf_path = storage_service.get_document_pdf_path(case_id, doc_id)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    doc = Document(
        document_id=doc_id,
        case_id=case_id,
        filename="akt.pdf",
        file_path=str(pdf_path),
        document_type="akt",
    )

    direct_pages = [
        PageData(
            page_number=1,
            text="Servitut om vejret til naboejendommen matr. nr. 5a tinglyst 15.06.2000.",
            confidence=0.9,
            extraction_method="pdfplumber_direct",
        )
    ]

    with get_session_ctx() as session:
        storage_service.save_document(session, doc)
        with patch("app.services.ocr_service._try_extract_text_direct", return_value=direct_pages) as mock_direct:
            with patch("app.services.ocr_service.run_ocrmypdf", side_effect=AssertionError("ocrmypdf should not run")):
                result = run_document_pipeline(session, case_id, doc)

    mock_direct.assert_called_once()
    assert result.reused_ocr_pdf is False
    assert result.reused_pages is False
    assert result.page_source == "pdfplumber_direct"
    assert result.direct_text_coverage == 1.0
    assert result.observability_path is not None
    observability_path = Path(result.observability_path)
    assert observability_path.exists()
    payload = json.loads(observability_path.read_text(encoding="utf-8"))
    assert payload["page_source"] == "pdfplumber_direct"
    assert payload["document_id"] == doc_id
    assert doc.parse_status == "ocr_done"
    assert doc.pages[0].extraction_method == "pdfplumber_direct"


def test_run_document_pipeline_falls_back_to_ocrmypdf_when_direct_fails(temp_storage):
    """Hvis direkte tekstudtræk returnerer None, kører ocrmypdf som normalt."""
    case_id = "case-test"
    doc_id = "doc-ocr-fallback"
    pdf_path = storage_service.get_document_pdf_path(case_id, doc_id)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    doc = Document(
        document_id=doc_id,
        case_id=case_id,
        filename="akt.pdf",
        file_path=str(pdf_path),
        document_type="akt",
    )

    ocr_pages = [PageData(page_number=1, text="OCR-ekstraheret tekst", confidence=0.85)]

    with get_session_ctx() as session:
        storage_service.save_document(session, doc)
        with patch("app.services.ocr_service._try_extract_text_direct", return_value=None):
            with patch("app.services.ocr_service.run_ocrmypdf") as mock_ocr:
                with patch("app.services.ocr_service.extract_pages_from_ocr_pdf", return_value=ocr_pages):
                    result = run_document_pipeline(session, case_id, doc)

    mock_ocr.assert_called_once()
    assert doc.pages[0].text == "OCR-ekstraheret tekst"
