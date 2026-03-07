"""OCR-first document processing using pymupdf for rendering and Tesseract for OCR."""
from pathlib import Path
from typing import List

from app.core.logging import get_logger
from app.models.document import PageData
from app.utils.text import clean_text

logger = get_logger(__name__)

# Tesseract config: danske tegn, PSM 3 = auto page segmentation
_TESSERACT_CONFIG = "--oem 1 --psm 3"
_TESSERACT_LANG = "dan+eng"

# DPI scale for pymupdf rendering — higher = bedre OCR kvalitet
_RENDER_SCALE = 3.0


def render_pdf_to_images(pdf_path: Path, output_dir: Path) -> List[Path]:
    """Render each PDF page to PNG. Returns list of image paths sorted by page number."""
    try:
        import fitz
    except ImportError:
        raise RuntimeError("pymupdf ikke installeret. Kør: uv sync")

    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    image_paths: List[Path] = []

    mat = fitz.Matrix(_RENDER_SCALE, _RENDER_SCALE)
    for i, page in enumerate(doc):
        page_number = i + 1
        pix = page.get_pixmap(matrix=mat)
        img_path = output_dir / f"page_{page_number}.png"
        pix.save(str(img_path))
        image_paths.append(img_path)
        logger.debug(f"Renderet side {page_number} → {img_path.name}")

    doc.close()
    logger.info(f"Renderet {len(image_paths)} sider fra {pdf_path.name}")
    return image_paths


def ocr_image(img_path: Path) -> tuple[str, float]:
    """
    Run Tesseract OCR on a single page image.
    Returns (text, mean_confidence) where confidence is 0.0–1.0.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise RuntimeError("pytesseract/pillow ikke installeret. Kør: uv sync")

    image = Image.open(img_path)

    # Get text + per-word confidence data
    data = pytesseract.image_to_data(
        image,
        lang=_TESSERACT_LANG,
        config=_TESSERACT_CONFIG,
        output_type=pytesseract.Output.DICT,
    )

    # Byg tekst og beregn gennemsnitlig confidence fra ord med conf > -1
    words = []
    confidences = []
    for i, word in enumerate(data["text"]):
        conf = int(data["conf"][i])
        if conf == -1:
            # Linjeskift/blok-separator
            if word.strip() == "" and words:
                words.append("\n")
        elif word.strip():
            words.append(word)
            confidences.append(conf)

    text = clean_text(" ".join(words))
    mean_conf = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0

    return text, mean_conf


def process_document(pdf_path: Path, doc_id: str, case_id: str, images_dir: Path) -> List[PageData]:
    """
    Full OCR pipeline for one document.

    1. Render hver PDF-side til PNG (pymupdf, 3x scale)
    2. Kør Tesseract OCR (dan+eng) på hvert billede
    3. Returner List[PageData] med tekst + confidence pr. side
    """
    image_paths = render_pdf_to_images(pdf_path, images_dir)

    pages: List[PageData] = []
    for img_path in image_paths:
        page_number = int(img_path.stem.split("_")[1])
        logger.info(f"OCR side {page_number}/{len(image_paths)} — {doc_id}")
        try:
            text, confidence = ocr_image(img_path)
            if confidence < 0.4:
                logger.warning(f"  Side {page_number}: lav confidence={confidence:.2f} — mulig dårlig scan")
            else:
                logger.info(f"  → {len(text)} tegn, conf={confidence:.2f}")
            pages.append(
                PageData(
                    page_number=page_number,
                    text=text,
                    image_path=str(img_path),
                    extraction_method="tesseract",
                    confidence=round(confidence, 3),
                )
            )
        except Exception as e:
            logger.error(f"OCR fejl side {page_number}: {e}")
            pages.append(
                PageData(
                    page_number=page_number,
                    text="",
                    image_path=str(img_path),
                    extraction_method="tesseract",
                    confidence=0.0,
                )
            )

    return pages
