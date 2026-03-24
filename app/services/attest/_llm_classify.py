"""Smal LLM-fallback til block-type klassifikation af UNKNOWN segmenter."""
from __future__ import annotations

import re

from app.core.logging import get_logger
from app.models.attest import AttestBlockType
from app.services.extraction.prompts import _load_prompt
from app.services.llm_service import generate_text
from app.services.extraction.llm_extractor import (
    _resolve_extraction_model,
    _resolve_extraction_provider,
)

logger = get_logger(__name__)

_VALID_TYPES = {t.value for t in AttestBlockType}


def llm_classify_block_type(text: str) -> AttestBlockType:
    """Kald LLM med smal prompt for at klassificere en ukendt attest-blok."""
    try:
        prompt_template = _load_prompt("classify_attest_block")
    except Exception:
        logger.warning("Prompt classify_attest_block.txt ikke fundet — returnerer UNKNOWN")
        return AttestBlockType.UNKNOWN

    truncated = text[:3000]
    prompt = prompt_template.replace("{block_text}", truncated)

    try:
        response = generate_text(
            prompt,
            max_tokens=50,
            provider=_resolve_extraction_provider(),
            default_model=_resolve_extraction_model(),
        )
    except Exception as exc:
        logger.warning("LLM-klassifikation fejlede: %s", exc)
        return AttestBlockType.UNKNOWN

    cleaned = response.strip().lower()
    # Udtræk første ord der matcher en gyldig type
    for token in re.split(r"[\s,;]+", cleaned):
        if token in _VALID_TYPES:
            return AttestBlockType(token)

    logger.warning("LLM returnerede ukendt block-type: %r", response[:100])
    return AttestBlockType.UNKNOWN
