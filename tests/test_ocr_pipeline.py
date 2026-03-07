"""
Tests for OCR pipeline: process_document → List[PageData]

OCRmyPDF og pdfplumber mockes — ingen rigtige PDF-filer kræves.
"""
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.document import PageData
from app.services.ocr_service import _estimate_confidence, extract_pages_from_ocr_pdf, process_document


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


# --- Regressions: ingen vision-referencer i OCR-service ---

def test_no_vision_references_in_ocr_service():
    source = Path("app/services/ocr_service.py").read_text(encoding="utf-8")
    assert "claude" not in source.lower(), "claude-reference fundet i ocr_service.py"
    assert "vision" not in source.lower(), "vision-reference fundet i ocr_service.py"
    assert "base64" not in source.lower(), "base64 (vision-legacy) fundet i ocr_service.py"


def test_extraction_method_is_ocrmypdf():
    page = PageData(page_number=1, text="test")
    assert page.extraction_method == "ocrmypdf"
