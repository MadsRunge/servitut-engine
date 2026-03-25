from datetime import date
import re
from typing import Optional


_DATE_RE = re.compile(r"(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>\d{4})")


def coerce_optional_str(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def coerce_optional_int(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = coerce_optional_str(value)
    if text is None:
        return None
    if not re.fullmatch(r"\d+", text):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def coerce_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip().lower()]
    return []


def parse_registered_at(value: object = None, date_reference: Optional[str] = None) -> Optional[date]:
    for candidate in (value, date_reference):
        parsed = _parse_date_candidate(candidate)
        if parsed:
            return parsed
    return None


def _parse_date_candidate(candidate: object) -> Optional[date]:
    if isinstance(candidate, date):
        return candidate
    if not isinstance(candidate, str):
        return None

    text = candidate.strip()
    if not text:
        return None

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass

    match = _DATE_RE.search(text)
    if not match:
        return None

    try:
        return date(
            year=int(match.group("year")),
            month=int(match.group("month")),
            day=int(match.group("day")),
        )
    except ValueError:
        return None
