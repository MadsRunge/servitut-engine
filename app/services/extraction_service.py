import json
from typing import List

from app.core.config import settings
from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.servitut import Evidence, Servitut
from app.services.llm_service import generate_text
from app.utils.ids import generate_servitut_id
from app.utils.text import has_servitut_keywords

logger = get_logger(__name__)


def _load_prompt() -> str:
    prompt_path = settings.prompts_path / "extract_servitut.txt"
    return prompt_path.read_text(encoding="utf-8")


def _prescreeen_chunks(chunks: List[Chunk]) -> List[Chunk]:
    """Return only chunks that pass keyword pre-screening."""
    relevant = [c for c in chunks if has_servitut_keywords(c.text, threshold=1)]
    logger.info(f"Pre-screening: {len(relevant)}/{len(chunks)} chunks pass keyword filter")
    return relevant


def _build_chunks_text(chunks: List[Chunk]) -> str:
    parts = []
    for c in chunks:
        parts.append(f"[Dok: {c.document_id} | Side {c.page} | Chunk {c.chunk_index}]\n{c.text}")
    return "\n\n---\n\n".join(parts)


def _parse_llm_response(response_text: str) -> list:
    """Extract JSON array from LLM response."""
    text = response_text.strip()
    # Find first '[' and last ']'
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        logger.warning("No JSON array found in LLM response")
        return []
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        logger.debug(f"Raw response: {text[:500]}")
        return []


def _find_evidence_chunk(chunks: List[Chunk], doc_id: str) -> List[Evidence]:
    """Find the chunks from a specific document to use as evidence."""
    doc_chunks = [c for c in chunks if c.document_id == doc_id]
    return [
        Evidence(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            page=c.page,
            text_excerpt=c.text[:300],
        )
        for c in doc_chunks[:3]
    ]


def extract_servitutter(
    chunks: List[Chunk],
    case_id: str,
) -> List[Servitut]:
    """Run pre-screening + LLM extraction on chunks, return Servitut list."""
    if not chunks:
        return []

    relevant_chunks = _prescreeen_chunks(chunks)
    if not relevant_chunks:
        logger.info("No relevant chunks after pre-screening")
        return []

    # Group by document
    doc_chunks: dict[str, List[Chunk]] = {}
    for c in relevant_chunks:
        doc_chunks.setdefault(c.document_id, []).append(c)

    prompt_template = _load_prompt()
    all_servitutter: List[Servitut] = []

    for doc_id, doc_chunk_list in doc_chunks.items():
        logger.info(f"Extracting from doc {doc_id} ({len(doc_chunk_list)} relevant chunks)")
        chunks_text = _build_chunks_text(doc_chunk_list)
        prompt = prompt_template.replace("{chunks_text}", chunks_text)

        try:
            response_text = generate_text(prompt, max_tokens=4096)
            extracted = _parse_llm_response(response_text)
        except Exception as e:
            logger.error(f"LLM extraction error for doc {doc_id}: {e}")
            continue

        for i, item in enumerate(extracted):
            srv_id = generate_servitut_id()
            evidence = _find_evidence_chunk(doc_chunk_list, doc_id)
            servitut = Servitut(
                servitut_id=srv_id,
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
                action_note=item.get("action_note"),
                confidence=float(item.get("confidence", 0.5) or 0.5),
                evidence=evidence,
            )
            all_servitutter.append(servitut)
            logger.info(f"Extracted: {servitut.title} (conf={servitut.confidence})")

    return all_servitutter
