from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
from queue import Queue
import threading
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.servitut import Evidence, Servitut
from app.services.extraction.progress import (
    ProgressCallback,
    _drain_progress_queue,
    _emit_progress,
)
from app.services.extraction.prompts import _load_prompt
from app.services.llm_service import generate_text
from app.utils.ids import generate_servitut_id
from app.utils.text import has_servitut_keywords

logger = get_logger(__name__)


def _prescreeen_chunks(chunks: List[Chunk]) -> List[Chunk]:
    relevant = [chunk for chunk in chunks if has_servitut_keywords(chunk.text, threshold=1)]
    logger.info(f"Pre-screening: {len(relevant)}/{len(chunks)} chunks pass keyword filter")
    return relevant


def _build_chunks_text(chunks: List[Chunk]) -> str:
    parts = []
    for chunk in chunks:
        parts.append(
            f"[Dok: {chunk.document_id} | Side {chunk.page} | Chunk {chunk.chunk_index}]\n{chunk.text}"
        )
    return "\n\n---\n\n".join(parts)


def _parse_llm_response(response_text: str) -> list:
    text = response_text.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        logger.warning("No JSON array found in LLM response")
        return []
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        logger.error(f"JSON parse error: {exc}")
        logger.debug(f"Raw response: {text[:500]}")
        return []


def _find_evidence_chunk(chunks: List[Chunk], doc_id: str) -> List[Evidence]:
    doc_chunks = [chunk for chunk in chunks if chunk.document_id == doc_id]
    return [
        Evidence(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            page=chunk.page,
            text_excerpt=chunk.text[:300],
        )
        for chunk in doc_chunks[:3]
    ]


def _extract_document_servitutter(
    doc_id: str,
    chunk_list: List[Chunk],
    case_id: str,
    prompt_template: str,
    source_type: str,
    progress_queue: Optional[Queue] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[Servitut]:
    worker_name = threading.current_thread().name
    logger.info(
        f"Extracting from doc {doc_id} ({len(chunk_list)} chunks, type={source_type})"
    )
    callback = progress_callback
    if progress_queue is not None:
        callback = lambda event: progress_queue.put(event)

    _emit_progress(
        callback,
        doc_id=doc_id,
        source_type=source_type,
        stage="running",
        progress=0.1,
        message="Forbereder prompt",
        worker=worker_name,
    )

    chunks_text = _build_chunks_text(chunk_list)
    prompt = prompt_template.replace("{chunks_text}", chunks_text)

    try:
        _emit_progress(
            callback,
            doc_id=doc_id,
            source_type=source_type,
            stage="requesting",
            progress=0.4,
            message="Sender LLM-kald",
            worker=worker_name,
        )
        response_text = generate_text(prompt, max_tokens=4096)
        _emit_progress(
            callback,
            doc_id=doc_id,
            source_type=source_type,
            stage="parsing",
            progress=0.75,
            message="Parser LLM-svar",
            worker=worker_name,
        )
        extracted = _parse_llm_response(response_text)
    except Exception as exc:
        logger.error(f"LLM extraction error for doc {doc_id}: {exc}")
        _emit_progress(
            callback,
            doc_id=doc_id,
            source_type=source_type,
            stage="failed",
            progress=1.0,
            message=f"Fejl: {exc}",
            worker=worker_name,
        )
        return []

    servitutter: List[Servitut] = []
    for i, item in enumerate(extracted):
        servitut = Servitut(
            servitut_id=generate_servitut_id(),
            case_id=case_id,
            source_document=doc_id,
            priority=i,
            date_reference=item.get("date_reference"),
            title=item.get("title"),
            summary=item.get("summary"),
            beneficiary=item.get("beneficiary"),
            disposition_type=item.get("disposition_type"),
            legal_type=item.get("legal_type"),
            construction_relevance=item.get("construction_relevance", False) or False,
            byggeri_markering=item.get("byggeri_markering"),
            action_note=item.get("action_note"),
            confidence=float(item.get("confidence", 0.5) or 0.5),
            evidence=_find_evidence_chunk(chunk_list, doc_id),
        )
        servitutter.append(servitut)
        logger.info(f"Extracted: {servitut.title} (conf={servitut.confidence})")

    _emit_progress(
        callback,
        doc_id=doc_id,
        source_type=source_type,
        stage="completed",
        progress=1.0,
        message=f"Færdig: {len(servitutter)} servitut(ter)",
        worker=worker_name,
        servitut_count=len(servitutter),
    )
    return servitutter


def _extract_from_doc_chunks(
    doc_chunks: dict[str, List[Chunk]],
    case_id: str,
    source_type: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[Servitut]:
    """Udtræk servitutter fra grupperede doc→chunks."""
    prompt_template = _load_prompt(source_type)
    ordered_doc_ids = list(doc_chunks.keys())
    max_workers = min(max(1, settings.EXTRACTION_MAX_CONCURRENCY), len(ordered_doc_ids))

    if max_workers == 1:
        all_servitutter: List[Servitut] = []
        for doc_id in ordered_doc_ids:
            _emit_progress(
                progress_callback,
                doc_id=doc_id,
                source_type=source_type,
                stage="queued",
                progress=0.0,
                message="Sat i kø",
            )
            all_servitutter.extend(
                _extract_document_servitutter(
                    doc_id,
                    doc_chunks[doc_id],
                    case_id,
                    prompt_template,
                    source_type,
                    progress_queue=None,
                    progress_callback=progress_callback,
                )
            )
        return all_servitutter

    logger.info(
        f"Parallel extraction enabled for {len(ordered_doc_ids)} documents "
        f"(max_workers={max_workers}, type={source_type})"
    )
    results_by_doc: dict[str, List[Servitut]] = {}
    progress_queue: Optional[Queue] = Queue() if progress_callback else None

    for doc_id in ordered_doc_ids:
        _emit_progress(
            progress_callback,
            doc_id=doc_id,
            source_type=source_type,
            stage="queued",
            progress=0.0,
            message="Sat i kø",
        )

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="extract-doc") as executor:
        futures = {
            executor.submit(
                _extract_document_servitutter,
                doc_id,
                doc_chunks[doc_id],
                case_id,
                prompt_template,
                source_type,
                progress_queue,
                None,
            ): doc_id
            for doc_id in ordered_doc_ids
        }
        pending = set(futures)
        while pending:
            done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
            _drain_progress_queue(progress_queue, progress_callback)
            for future in done:
                doc_id = futures[future]
                try:
                    results_by_doc[doc_id] = future.result()
                except Exception as exc:
                    logger.error(f"Parallel extraction worker failed for doc {doc_id}: {exc}")
                    results_by_doc[doc_id] = []
        _drain_progress_queue(progress_queue, progress_callback)

    all_servitutter: List[Servitut] = []
    for doc_id in ordered_doc_ids:
        all_servitutter.extend(results_by_doc.get(doc_id, []))
    return all_servitutter
