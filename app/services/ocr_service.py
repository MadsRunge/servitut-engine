"""
OCR-first dokumentbehandling.

Pipeline: original.pdf → ocrmypdf → ocr.pdf (PDF med tekstlag) → pdfplumber → List[PageData]

Resten af systemet må kun kende PageData — ikke OCR-engine.
"""
import shutil
from pathlib import Path
from typing import List

from app.core.config import settings
from app.core.logging import get_logger
from app.models.document import PageData
from app.utils.text import clean_text

logger = get_logger(__name__)


def _estimate_confidence(text: str) -> float:
    """
    Estimér OCR-kvalitet ud fra tekstindhold.
    Blank side eller ren støj → lav confidence; læsbar tekst → høj confidence.
    """
    if not text:
        return 0.0
    alnum_chars = sum(c.isalnum() for c in text)
    ratio = alnum_chars / len(text)
    # ratio ~0.45 for normal tekst, <0.15 for støj
    return round(min(1.0, max(0.0, (ratio - 0.10) / 0.40)), 3)


def summarize_pages(pages: List[PageData]) -> tuple[int, int, int]:
    """Returnér (blanke, lave, ok) sideantal til let UI/statusbrug."""
    blank = sum(1 for page in pages if page.confidence == 0.0)
    low = sum(1 for page in pages if 0.0 < page.confidence < 0.4)
    ok = len(pages) - blank - low
    return blank, low, ok


def run_ocrmypdf(pdf_path: Path, ocr_pdf_path: Path) -> None:
    """
    Kør ocrmypdf på original PDF og gem OCR-resultatet som ocr.pdf.
    Tilføjer tekstlag til scannede sider; springer sider over der allerede har tekst.
    """
    try:
        import ocrmypdf
    except ImportError:
        raise RuntimeError("ocrmypdf ikke installeret. Kør: brew install ocrmypdf")

    ocr_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Kører ocrmypdf: {pdf_path.name} → {ocr_pdf_path.name}")

    try:
        ocrmypdf.ocr(
            str(pdf_path),
            str(ocr_pdf_path),
            language=settings.OCR_LANGUAGE,
            deskew=settings.OCR_DESKEW,
            skip_text=True,
            progress_bar=False,
            jobs=1,
        )
    except ocrmypdf.exceptions.PriorOcrFoundError:
        # Dokumentet har allerede et fuldt tekstlag — brug original som OCR-output
        logger.info("Dokument har allerede OCR-tekstlag — kopierer original")
        shutil.copy(str(pdf_path), str(ocr_pdf_path))


def extract_pages_from_ocr_pdf(ocr_pdf_path: Path) -> List[PageData]:
    """Udtræk side-tekst fra OCR-behandlet PDF vha. pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber ikke installeret. Kør: uv sync")

    pages: List[PageData] = []
    with pdfplumber.open(str(ocr_pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            page_number = i + 1
            raw_text = page.extract_text() or ""
            text = clean_text(raw_text)
            confidence = _estimate_confidence(text)
            pages.append(
                PageData(
                    page_number=page_number,
                    text=text,
                    extraction_method="ocrmypdf",
                    confidence=confidence,
                )
            )
            logger.debug(f"  Side {page_number}: {len(text)} tegn, conf={confidence:.2f}")

    logger.info(f"Udtrukket {len(pages)} sider fra {ocr_pdf_path.name}")
    return pages


def process_document(pdf_path: Path, doc_id: str, case_id: str, ocr_pdf_path: Path) -> List[PageData]:
    """
    Komplet OCR-pipeline for ét dokument.

    1. Kør ocrmypdf på original.pdf → ocr.pdf
    2. Udtræk side-tekst fra ocr.pdf med pdfplumber
    3. Returner List[PageData]
    """
    run_ocrmypdf(pdf_path, ocr_pdf_path)
    pages = extract_pages_from_ocr_pdf(ocr_pdf_path)

    blank, low, _ = summarize_pages(pages)
    logger.info(
        f"OCR færdig: {len(pages)} sider | {blank} blanke | {low} lav-conf | doc={doc_id}"
    )
    return pages
