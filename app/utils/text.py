import re
from typing import List


# Danish servitut keywords for pre-screening
SERVITUT_KEYWORDS = [
    "servitut",
    "deklaration",
    "tinglyst",
    "påtaleberettiget",
    "byggelinje",
    "fredning",
    "vejret",
    "færdselsret",
    "ledningsret",
    "hegnsyn",
    "naturgasledning",
    "el-ledning",
    "kloakledning",
    "vandledning",
    "udstykningsforbud",
    "bebyggelsesprocent",
    "lokalplan",
]

# Patterns for date/reference extraction
DATE_PATTERNS = [
    r"\d{2}\.\d{2}\.\d{4}",          # DD.MM.YYYY
    r"\d{4}-\d{2}-\d{2}",             # YYYY-MM-DD
    r"\d{2}/\d{2}-\d{4}",             # DD/MM-YYYY
    r"\d{1,2}\.\s*\w+\s*\d{4}",       # D. måned YYYY
]

LOBENUMMER_PATTERN = re.compile(r"\d{6,}-\d+")


def clean_text(text: str) -> str:
    """Remove excessive whitespace and normalize line endings."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def normalize_danish(text: str) -> str:
    """Normalize common OCR errors in Danish text."""
    replacements = {
        "ae": "æ",
        "oe": "ø",
        "aa": "å",
    }
    for wrong, correct in replacements.items():
        # Only replace when clearly a Danish word issue — skip for now
        pass
    return text


def has_servitut_keywords(text: str, threshold: int = 1) -> bool:
    """Return True if text contains at least `threshold` servitut-related keywords."""
    text_lower = text.lower()
    count = sum(1 for kw in SERVITUT_KEYWORDS if kw in text_lower)
    return count >= threshold


def extract_date_references(text: str) -> List[str]:
    """Extract date strings from text."""
    results = []
    for pattern in DATE_PATTERNS:
        results.extend(re.findall(pattern, text))
    return list(set(results))


def split_into_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs on double newlines."""
    paragraphs = re.split(r"\n{2,}", text)
    return [p.strip() for p in paragraphs if p.strip()]
