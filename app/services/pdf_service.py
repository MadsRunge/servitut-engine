from pathlib import Path
from typing import List

from app.core.logging import get_logger
from app.models.document import PageData
from app.utils.text import clean_text

logger = get_logger(__name__)

# Threshold below which a page is flagged as OCR candidate
MIN_CHARS_PER_PAGE = 50


def parse_pdf(file_path: Path) -> List[PageData]:
    """Parse a PDF and return a list of PageData, one per page."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber is not installed. Run: pip install pdfplumber")

    pages: List[PageData] = []

    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_number = i + 1
            try:
                raw_text = page.extract_text() or ""
                text = clean_text(raw_text)
                char_count = len(text)

                if char_count < MIN_CHARS_PER_PAGE:
                    extraction_method = "ocr_candidate"
                    confidence = 0.3
                    logger.warning(
                        f"Page {page_number} has only {char_count} chars — OCR candidate"
                    )
                else:
                    extraction_method = "pdfplumber"
                    confidence = 1.0

                pages.append(
                    PageData(
                        page_number=page_number,
                        text=text,
                        extraction_method=extraction_method,
                        confidence=confidence,
                    )
                )
            except Exception as e:
                logger.error(f"Error extracting page {page_number}: {e}")
                pages.append(
                    PageData(
                        page_number=page_number,
                        text="",
                        extraction_method="error",
                        confidence=0.0,
                    )
                )

    logger.info(f"Parsed {len(pages)} pages from {file_path.name}")
    return pages
