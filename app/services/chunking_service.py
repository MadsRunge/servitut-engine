import re
from typing import List

from app.core.config import settings
from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.document import PageData
from app.utils.ids import generate_chunk_id
from app.utils.text import split_into_paragraphs

logger = get_logger(__name__)

# DSS-metadata-headers er administrative forsider der aldrig indeholder servitutindhold.
# Format: "DSS 88303021 76_AR-A 31 Bulk Sort / Hvid 271876"
_DSS_HEADER_RE = re.compile(
    r"^dss\s+\d+.{0,50}bulk\s+(sort|hvid)\b", re.IGNORECASE
)


def _is_administrative_page(text: str) -> bool:
    """Returnér True for sider der med sikkerhed ikke indeholder servitutindhold."""
    return bool(_DSS_HEADER_RE.match(text.strip()[:80]))


def chunk_pages(pages: List[PageData], doc_id: str, case_id: str) -> List[Chunk]:
    """Split pages into chunks using paragraph-based splitting."""
    chunks: List[Chunk] = []
    chunk_index = 0
    max_size = settings.MAX_CHUNK_SIZE
    overlap = settings.CHUNK_OVERLAP

    for page in pages:
        if not page.text:
            continue
        if _is_administrative_page(page.text):
            logger.debug("Springer administrativ side over: dok=%s side=%d", doc_id, page.page_number)
            continue

        paragraphs = split_into_paragraphs(page.text)
        current_text = ""
        current_start = 0

        for para in paragraphs:
            # If adding this paragraph would exceed max_size, flush current chunk
            if current_text and len(current_text) + len(para) + 2 > max_size:
                _flush_chunk(
                    chunks, current_text, current_start, doc_id, case_id,
                    page.page_number, chunk_index
                )
                chunk_index += 1
                # Carry overlap from end of previous chunk
                overlap_text = current_text[-overlap:] if overlap else ""
                current_start = len(current_text) - len(overlap_text)
                current_text = overlap_text + "\n\n" + para if overlap_text else para
            else:
                current_text = (current_text + "\n\n" + para).strip() if current_text else para

        if current_text:
            _flush_chunk(
                chunks, current_text, current_start, doc_id, case_id,
                page.page_number, chunk_index
            )
            chunk_index += 1

    logger.info(f"Created {len(chunks)} chunks for doc {doc_id}")
    return chunks


def _flush_chunk(
    chunks: List[Chunk],
    text: str,
    char_start: int,
    doc_id: str,
    case_id: str,
    page: int,
    chunk_index: int,
) -> None:
    chunk_id = generate_chunk_id(doc_id, page, chunk_index)
    chunks.append(
        Chunk(
            chunk_id=chunk_id,
            document_id=doc_id,
            case_id=case_id,
            page=page,
            text=text,
            chunk_index=chunk_index,
            char_start=char_start,
            char_end=char_start + len(text),
        )
    )
