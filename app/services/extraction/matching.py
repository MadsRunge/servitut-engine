import re
from typing import Optional

from app.models.servitut import Servitut


def _extract_date_components(date_ref: Optional[str]) -> dict:
    """Udtræk år, dato og løbenummer fra date_reference til brug ved matching."""
    if not date_ref:
        return {}

    result = {}

    lob = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})-(\d+(?:-\d+)+)", date_ref)
    if lob:
        raw_date = lob.group(1)
        parts = raw_date.split(".")
        result["full_date"] = f"{parts[0].zfill(2)}.{parts[1].zfill(2)}.{parts[2]}"
        result["løbenummer_suffix"] = lob.group(2)
        result["year"] = parts[2]
        return result

    date_m = re.search(r"(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})", date_ref)
    if date_m:
        d, m, y = date_m.groups()
        result["full_date"] = f"{d.zfill(2)}.{m.zfill(2)}.{y}"
        result["year"] = y
        return result

    year_m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", date_ref)
    if year_m:
        result["year"] = year_m.group(1)

    return result


def _servitut_matches(
    canonical: Servitut,
    akt_srv: Servitut,
    canonical_years: dict[str, int] | None = None,
) -> bool:
    """Returner True hvis akt_srv sandsynligvis er samme servitut som canonical."""
    c = _extract_date_components(canonical.date_reference)
    a = _extract_date_components(akt_srv.date_reference)

    if not c or not a:
        return False

    if c.get("løbenummer_suffix") and a.get("løbenummer_suffix"):
        return c["løbenummer_suffix"] == a["løbenummer_suffix"]

    if c.get("full_date") and a.get("full_date"):
        return c["full_date"] == a["full_date"]

    if c.get("year") and a.get("year") and c["year"] == a["year"]:
        if canonical_years and canonical_years.get(c["year"], 0) == 1:
            return True

    return False
