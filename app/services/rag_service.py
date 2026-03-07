import re
from typing import List

from app.models.chunk import Chunk
from app.models.servitut import Servitut


def extract_keywords(servitut: Servitut) -> List[str]:
    """Extract keywords from servitut title and summary."""
    text = " ".join(filter(None, [servitut.title, servitut.summary, servitut.beneficiary]))
    # Simple tokenization: split on non-word chars, keep words 3+ chars
    words = re.findall(r"\b\w{3,}\b", text.lower())
    # Deduplicate while preserving order
    seen = set()
    keywords = []
    for w in words:
        if w not in seen:
            seen.add(w)
            keywords.append(w)
    return keywords


def score_chunk(chunk_text: str, keywords: List[str]) -> float:
    """Score a chunk by keyword overlap."""
    if not keywords:
        return 0.0
    text_lower = chunk_text.lower()
    matches = sum(1 for kw in keywords if kw in text_lower)
    return matches / len(keywords)


def find_relevant_chunks(
    servitut: Servitut,
    all_chunks: List[Chunk],
    top_k: int = 5,
) -> List[Chunk]:
    """Return top_k chunks most relevant to the given servitut."""
    keywords = extract_keywords(servitut)
    if not keywords:
        return []

    # Filter to source document first if possible
    doc_chunks = [c for c in all_chunks if c.document_id == servitut.source_document]
    search_pool = doc_chunks if doc_chunks else all_chunks

    scored = [(score_chunk(c.text, keywords), c) for c in search_pool]
    scored = [(s, c) for s, c in scored if s > 0.0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]
