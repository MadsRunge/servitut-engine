"""
OCR-first dokumentbehandling.

Pipeline: original.pdf → ocrmypdf → ocr.pdf (PDF med tekstlag) → pdfplumber → List[PageData]

Resten af systemet må kun kende PageData — ikke OCR-engine.
"""
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

from sqlmodel import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.document import Document, PageData
from app.services import pipeline_observability, storage_service
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
    page_source: str
    direct_text_coverage: float | None
    total_duration_seconds: float
    observability_path: str | None


def _resolve_ocr_jobs() -> int:
    configured_jobs = settings.OCR_JOBS
    if configured_jobs and configured_jobs > 0:
        return configured_jobs
    return max(1, min(os.cpu_count() or 1, 4))


def _measure_direct_text_coverage(pages: List[PageData]) -> float:
    if not pages:
        return 0.0
    usable_pages = sum(1 for page in pages if len(page.text) >= 50 and page.confidence >= 0.3)
    return usable_pages / len(pages)


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
    Hvis PDF'en overstiger OCR_BATCH_SIZE sider, processeres den i batches for at
    begrænse memory-forbruget.
    """
    try:
        import ocrmypdf
    except ImportError:
        raise RuntimeError("ocrmypdf ikke installeret. Kør: brew install ocrmypdf")

    ocr_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    batch_size = settings.OCR_BATCH_SIZE
    if batch_size > 0:
        import fitz

        source = fitz.open(str(pdf_path))
        total_pages = source.page_count
        source.close()
        if total_pages > batch_size:
            _run_ocrmypdf_batched(pdf_path, ocr_pdf_path, total_pages, batch_size)
            return

    _run_ocrmypdf_single(pdf_path, ocr_pdf_path)


def _run_ocrmypdf_single(pdf_path: Path, ocr_pdf_path: Path) -> None:
    import ocrmypdf

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
        logger.info("Dokument har allerede OCR-tekstlag — kopierer original")
        shutil.copy(str(pdf_path), str(ocr_pdf_path))


def _run_ocrmypdf_batched(
    pdf_path: Path, ocr_pdf_path: Path, total_pages: int, batch_size: int
) -> None:
    import fitz
    import ocrmypdf
    import tempfile

    logger.info(
        f"Kører batch-OCR: {pdf_path.name} ({total_pages} sider, batch={batch_size})"
    )
    source = fitz.open(str(pdf_path))
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            ocr_parts: list[Path] = []

            for batch_index, batch_start in enumerate(range(0, total_pages, batch_size)):
                batch_end = min(batch_start + batch_size - 1, total_pages - 1)
                batch_num = batch_index + 1
                logger.info(f"  Batch {batch_num}: side {batch_start + 1}–{batch_end + 1}")

                batch_pdf_path = tmp / f"batch_{batch_num:03d}.pdf"
                batch_pdf = fitz.open()
                try:
                    batch_pdf.insert_pdf(source, from_page=batch_start, to_page=batch_end)
                    batch_pdf.save(str(batch_pdf_path))
                finally:
                    batch_pdf.close()

                batch_ocr_path = tmp / f"batch_{batch_num:03d}_ocr.pdf"
                try:
                    ocrmypdf.ocr(
                        str(batch_pdf_path),
                        str(batch_ocr_path),
                        language=settings.OCR_LANGUAGE,
                        deskew=settings.OCR_DESKEW,
                        skip_text=True,
                        progress_bar=False,
                        jobs=_resolve_ocr_jobs(),
                    )
                except ocrmypdf.exceptions.PriorOcrFoundError:
                    logger.info(f"  Batch {batch_num} har allerede OCR-tekstlag — bruger original")
                    shutil.copy(str(batch_pdf_path), str(batch_ocr_path))

                ocr_parts.append(batch_ocr_path)

            merged = fitz.open()
            try:
                for part_path in ocr_parts:
                    part_pdf = fitz.open(str(part_path))
                    merged.insert_pdf(part_pdf)
                    part_pdf.close()
                merged.save(str(ocr_pdf_path))
            finally:
                merged.close()
    finally:
        source.close()

    logger.info(f"Batch-OCR færdig: {total_pages} sider → {ocr_pdf_path.name}")


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


_DIRECT_TEXT_MIN_COVERAGE = 0.75  # fraction of pages that must have usable text to skip OCR


def _try_extract_text_direct(pdf_path: Path) -> List[PageData] | None:
    """
    Forsøg tekstudtræk direkte fra original-PDF med pdfplumber uden at køre ocrmypdf.

    Returnerer List[PageData] hvis mindst _DIRECT_TEXT_MIN_COVERAGE af siderne har
    brugbar tekst (≥50 tegn med rimelig confidence). Returnerer None hvis PDF'en
    kræver OCR (for mange billedsider uden tekstlag).
    """
    try:
        import pdfplumber
    except ImportError:
        return None

    try:
        pages: List[PageData] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, page in enumerate(pdf.pages):
                raw_text = page.extract_text() or ""
                text = clean_text(raw_text)
                confidence = _estimate_confidence(text)
                pages.append(
                    PageData(
                        page_number=i + 1,
                        text=text,
                        extraction_method="pdfplumber_direct",
                        confidence=confidence,
                    )
                )
    except Exception as exc:
        logger.debug("Direkte tekstudtræk fejlede for %s: %s", pdf_path.name, exc)
        return None

    if not pages:
        return None

    usable = sum(1 for p in pages if len(p.text) >= 50 and p.confidence >= 0.3)
    coverage = usable / len(pages)
    if coverage >= _DIRECT_TEXT_MIN_COVERAGE:
        logger.info(
            "Direkte tekstudtræk: %d/%d sider brugbare (%.0f%%) — springer ocrmypdf over for %s",
            usable,
            len(pages),
            coverage * 100,
            pdf_path.name,
        )
        return pages

    logger.info(
        "Direkte tekstudtræk: %.0f%% dækning < %.0f%% tærskel — kører ocrmypdf for %s",
        coverage * 100,
        _DIRECT_TEXT_MIN_COVERAGE * 100,
        pdf_path.name,
    )
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
    session: Session,
    case_id: str,
    doc_id: str,
    pdf_path: Path,
    ocr_pdf_path: Path,
    force: bool = False,
) -> tuple[List[PageData], bool, bool, str, float | None]:
    pages_path = storage_service.get_ocr_path(case_id, doc_id)

    # Freshness check: pages are fresh when newer than original PDF.
    # If ocr_pdf exists, also require pages to be newer than ocr_pdf.
    # If ocr_pdf does NOT exist (direct path was used last time), only check against original PDF.
    if not force:
        if ocr_pdf_path.exists():
            reused_pages = _artifact_is_fresh(pages_path, [pdf_path, ocr_pdf_path])
        else:
            reused_pages = _artifact_is_fresh(pages_path, [pdf_path])
    else:
        reused_pages = False

    reused_ocr_pdf = not force and _artifact_is_fresh(ocr_pdf_path, [pdf_path])

    if reused_pages:
        logger.info("Genbruger eksisterende OCR-sider for %s", doc_id)
        pages = storage_service.load_ocr_pages(session, case_id, doc_id)
        direct_text_coverage = (
            _measure_direct_text_coverage(pages)
            if all(page.extraction_method == "pdfplumber_direct" for page in pages)
            else None
        )
        return pages, reused_ocr_pdf, True, "reused_pages", direct_text_coverage

    # Fast path: prøv pdfplumber direkte på original-PDF
    direct_pages = _try_extract_text_direct(pdf_path)
    if direct_pages is not None:
        storage_service.save_ocr_pages(session, case_id, doc_id, direct_pages)
        return direct_pages, False, False, "pdfplumber_direct", _measure_direct_text_coverage(direct_pages)

    # Fuld OCR-sti via ocrmypdf
    if reused_ocr_pdf:
        logger.info("Genbruger eksisterende ocr.pdf for %s", doc_id)
    else:
        run_ocrmypdf(pdf_path, ocr_pdf_path)
    pages = extract_pages_from_ocr_pdf(ocr_pdf_path)
    storage_service.save_ocr_pages(session, case_id, doc_id, pages)
    return pages, reused_ocr_pdf, False, ("reused_ocr_pdf" if reused_ocr_pdf else "ocrmypdf"), None


def _load_or_create_chunks(
    session: Session,
    case_id: str,
    doc_id: str,
    pages: List[PageData],
    force: bool = False,
) -> tuple[List[Chunk], bool]:
    # Chunks gemmes nu i DB; tjek eksistens via DB i stedet for disk-mtime
    if not force:
        existing = storage_service.load_chunks(session, case_id, doc_id)
        if existing:
            logger.info("Genbruger eksisterende chunks for %s", doc_id)
            return existing, True

    chunks = chunk_pages(pages, doc_id, case_id)
    storage_service.save_chunks(session, case_id, doc_id, chunks)
    return chunks, False


def run_document_pipeline(
    session: Session,
    case_id: str,
    doc: Document,
    force: bool = False,
    run_id: str | None = None,
) -> OcrPipelineResult:
    pdf_path = Path(doc.file_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF-fil ikke fundet på disk: {pdf_path}")

    pipeline_started_at = time.perf_counter()
    ocr_pdf_path = storage_service.get_ocr_pdf_path(case_id, doc.document_id)
    pages_started_at = time.perf_counter()
    pages, reused_ocr_pdf, reused_pages, page_source, direct_text_coverage = _load_or_create_pages(
        session=session,
        case_id=case_id,
        doc_id=doc.document_id,
        pdf_path=pdf_path,
        ocr_pdf_path=ocr_pdf_path,
        force=force,
    )
    page_stage_duration = round(time.perf_counter() - pages_started_at, 3)
    chunks_started_at = time.perf_counter()
    chunks, reused_chunks = _load_or_create_chunks(
        session=session,
        case_id=case_id,
        doc_id=doc.document_id,
        pages=pages,
        force=force,
    )
    chunk_stage_duration = round(time.perf_counter() - chunks_started_at, 3)
    total_duration = round(time.perf_counter() - pipeline_started_at, 3)

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
    storage_service.save_document(session, doc)

    observability_payload = {
        "pipeline": "ocr",
        "case_id": case_id,
        "document_id": doc.document_id,
        "filename": doc.filename,
        "document_type": doc.document_type,
        "page_count": len(pages),
        "chunk_count": len(chunks),
        "blank_pages": blank,
        "low_conf_pages": low,
        "page_source": page_source,
        "direct_text_coverage": round(direct_text_coverage, 3) if direct_text_coverage is not None else None,
        "reused_ocr_pdf": reused_ocr_pdf,
        "reused_pages": reused_pages,
        "reused_chunks": reused_chunks,
        "ocr_jobs": _resolve_ocr_jobs(),
        "ocr_batch_size": settings.OCR_BATCH_SIZE,
        "page_stage_duration_seconds": page_stage_duration,
        "chunk_stage_duration_seconds": chunk_stage_duration,
        "total_duration_seconds": total_duration,
    }
    observability_path = pipeline_observability.write_ocr_run_summary(
        case_id,
        doc.document_id,
        observability_payload,
        run_id=run_id,
    )
    logger.info(
        "OCR observability: case=%s doc=%s source=%s pages=%d chunks=%d direct_coverage=%s total=%.3fs path=%s",
        case_id,
        doc.document_id,
        page_source,
        len(pages),
        len(chunks),
        f"{direct_text_coverage:.0%}" if direct_text_coverage is not None else "n/a",
        total_duration,
        observability_path,
    )

    return OcrPipelineResult(
        pages=pages,
        chunks=chunks,
        blank_pages=blank,
        low_conf_pages=low,
        reused_ocr_pdf=reused_ocr_pdf,
        reused_pages=reused_pages,
        reused_chunks=reused_chunks,
        page_source=page_source,
        direct_text_coverage=round(direct_text_coverage, 3) if direct_text_coverage is not None else None,
        total_duration_seconds=total_duration,
        observability_path=str(observability_path),
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
