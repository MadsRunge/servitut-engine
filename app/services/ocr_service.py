"""
OCR-first dokumentbehandling.

Pipeline: original.pdf → ocrmypdf → ocr.pdf (PDF med tekstlag) → pdfplumber → List[PageData]

Resten af systemet må kun kende PageData — ikke OCR-engine.
"""
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List

from app.core.config import settings
from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.document import Document, PageData
from app.services import storage_service
from app.services.chunking_service import chunk_pages
from app.services.document_classifier import classify_document
from app.utils.text import clean_text

logger = get_logger(__name__)


@dataclass
class OcrPipelineResult:
    pages: List[PageData]
    chunks: List[Chunk]
    blank_pages: int
    low_conf_pages: int
    reused_ocr_pdf: bool
    reused_pages: bool
    reused_chunks: bool


def _resolve_ocr_jobs() -> int:
    configured_jobs = settings.OCR_JOBS
    if configured_jobs and configured_jobs > 0:
        return configured_jobs
    return max(1, min(os.cpu_count() or 1, 4))


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
            jobs=_resolve_ocr_jobs(),
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


def _preserve_known_document_type(document_type: str) -> str | None:
    if document_type in {"akt", "tinglysningsattest"}:
        return document_type
    return None


def _artifact_is_fresh(artifact_path: Path, dependency_paths: list[Path]) -> bool:
    if not artifact_path.exists():
        return False

    artifact_mtime = artifact_path.stat().st_mtime
    for dependency_path in dependency_paths:
        if not dependency_path.exists():
            return False
        if artifact_mtime < dependency_path.stat().st_mtime:
            return False
    return True


def _load_or_create_pages(
    case_id: str,
    doc_id: str,
    pdf_path: Path,
    ocr_pdf_path: Path,
    force: bool = False,
) -> tuple[List[PageData], bool, bool]:
    pages_path = storage_service.get_ocr_path(case_id, doc_id)
    reused_ocr_pdf = not force and _artifact_is_fresh(ocr_pdf_path, [pdf_path])
    reused_pages = (
        not force and _artifact_is_fresh(pages_path, [pdf_path, ocr_pdf_path])
    )

    if reused_ocr_pdf:
        logger.info("Genbruger eksisterende ocr.pdf for %s", doc_id)
    else:
        run_ocrmypdf(pdf_path, ocr_pdf_path)

    if reused_pages:
        logger.info("Genbruger eksisterende OCR-sider for %s", doc_id)
        pages = storage_service.load_ocr_pages(case_id, doc_id)
    else:
        pages = extract_pages_from_ocr_pdf(ocr_pdf_path)
        storage_service.save_ocr_pages(case_id, doc_id, pages)

    return pages, reused_ocr_pdf, reused_pages


def _load_or_create_chunks(
    case_id: str,
    doc_id: str,
    pages: List[PageData],
    force: bool = False,
) -> tuple[List[Chunk], bool]:
    pages_path = storage_service.get_ocr_path(case_id, doc_id)
    chunks_path = storage_service.get_chunks_path(case_id, doc_id)
    reused_chunks = not force and _artifact_is_fresh(chunks_path, [pages_path])

    if reused_chunks:
        logger.info("Genbruger eksisterende chunks for %s", doc_id)
        return storage_service.load_chunks(case_id, doc_id), True

    chunks = chunk_pages(pages, doc_id, case_id)
    storage_service.save_chunks(case_id, doc_id, chunks)
    return chunks, False


def run_document_pipeline(case_id: str, doc: Document, force: bool = False) -> OcrPipelineResult:
    pdf_path = Path(doc.file_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF-fil ikke fundet på disk: {pdf_path}")

    ocr_pdf_path = storage_service.get_ocr_pdf_path(case_id, doc.document_id)
    pages, reused_ocr_pdf, reused_pages = _load_or_create_pages(
        case_id=case_id,
        doc_id=doc.document_id,
        pdf_path=pdf_path,
        ocr_pdf_path=ocr_pdf_path,
        force=force,
    )
    chunks, reused_chunks = _load_or_create_chunks(
        case_id=case_id,
        doc_id=doc.document_id,
        pages=pages,
        force=force,
    )

    blank, low, _ = summarize_pages(pages)
    doc.pages = pages
    doc.page_count = len(pages)
    doc.chunk_count = len(chunks)
    doc.ocr_blank_pages = blank
    doc.ocr_low_conf_pages = low
    doc.document_type = classify_document(
        doc.filename,
        pages=pages,
        requested_type=_preserve_known_document_type(doc.document_type),
    )
    doc.parse_status = "ocr_done"
    storage_service.save_document(doc)

    return OcrPipelineResult(
        pages=pages,
        chunks=chunks,
        blank_pages=blank,
        low_conf_pages=low,
        reused_ocr_pdf=reused_ocr_pdf,
        reused_pages=reused_pages,
        reused_chunks=reused_chunks,
    )


def format_pipeline_result_message(result: OcrPipelineResult) -> str:
    reused_parts = []
    if result.reused_ocr_pdf:
        reused_parts.append("ocr.pdf")
    if result.reused_pages:
        reused_parts.append("OCR-sider")
    if result.reused_chunks:
        reused_parts.append("chunks")

    if reused_parts:
        reuse_text = f"genbrugte {', '.join(reused_parts)}"
    else:
        reuse_text = "fuld OCR-kørsel"

    return f"{len(result.pages)} sider, {len(result.chunks)} chunks ({reuse_text})"
