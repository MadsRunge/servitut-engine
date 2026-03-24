"""Deterministisk scope-resolution for RegistrationEntry-objekter.

Trin 4 i attest-pipeline v2:
  RegistrationEntry[] + case_matrikler → berigede entries med scope_type,
  scope_confidence, applies_to_parcel_numbers, applies_to_primary_parcel.

Entries med scope_confidence < REVIEW_THRESHOLD flagges med "review_required".
"""
from __future__ import annotations

import re
from typing import List, Optional

from app.core.logging import get_logger
from app.models.servitut import Servitut

logger = get_logger(__name__)

REVIEW_THRESHOLD = 0.50

# scope_type strenge (spejler ScopeType enum)
_SCOPE_EXPLICIT  = "explicit_parcel_list"
_SCOPE_WHOLE     = "whole_property"
_SCOPE_AREA      = "area_description"
_SCOPE_UNKNOWN   = "unknown"

_WHOLE_PROPERTY_PATTERNS = [
    re.compile(r"hele\s+ejendommen", re.IGNORECASE),
    re.compile(r"samtlige\s+parceller", re.IGNORECASE),
    re.compile(r"\bal\s+grund\b", re.IGNORECASE),
    re.compile(r"hele\s+matriklen", re.IGNORECASE),
    re.compile(r"all\s+parcels", re.IGNORECASE),
]

_PARCEL_PATTERN = re.compile(r"\b(\d+[a-zæøå]{0,3})\b", re.IGNORECASE)

# Geografi-ord der indikerer AREA_DESCRIPTION
_AREA_SIGNALS = re.compile(
    r"\b(vej|sti|å|sø|skov|mark|eng|gyde|havn|bane|grøft)\b",
    re.IGNORECASE,
)


def _normalize_parcel(p: str) -> str:
    return p.strip().lower()


def _extract_parcel_refs(text: str) -> List[str]:
    if not text:
        return []
    refs = [m.group(1).lower() for m in _PARCEL_PATTERN.finditer(text)]
    seen: dict[str, None] = {}
    for r in refs:
        seen[r] = None
    return list(seen.keys())


def _is_whole_property(text: str) -> bool:
    return any(p.search(text) for p in _WHOLE_PROPERTY_PATTERNS)


def _has_area_signal(text: str) -> bool:
    return bool(_AREA_SIGNALS.search(text))


def _match_parcels(
    candidates: List[str],
    case_matrikler: List[str],
) -> tuple[List[str], str]:
    """Match kandidater mod case_matrikler.

    Returnerer (matched, match_quality):
      "all_matched"          — alle kandidater matchede
      "partial_match"        — mindst én matchede
      "historical_unmapped"  — ingen match (muligt historisk matrikel)
      "no_match"             — ingen match og ingen kandidater
    """
    if not candidates:
        return ([], "no_match")

    normalized_case = {_normalize_parcel(m) for m in case_matrikler}
    matched = [c for c in candidates if _normalize_parcel(c) in normalized_case]

    if len(matched) == len(candidates):
        return (matched, "all_matched")
    if matched:
        return (matched, "partial_match")
    return (candidates, "historical_unmapped")


def _scope_confidence(scope_type: str, match_quality: str, is_fanout_inherited: bool) -> float:
    if is_fanout_inherited:
        return 0.35

    table: dict[tuple[str, str], float] = {
        (_SCOPE_EXPLICIT, "all_matched"):          0.95,
        (_SCOPE_EXPLICIT, "partial_match"):        0.75,
        (_SCOPE_WHOLE,    "any"):                  0.80,
        (_SCOPE_AREA,     "with_signal"):          0.60,
        (_SCOPE_AREA,     "no_signal"):            0.40,
        (_SCOPE_EXPLICIT, "historical_unmapped"):  0.50,
        (_SCOPE_UNKNOWN,  "any"):                  0.10,
    }
    key = (scope_type, match_quality)
    if key in table:
        return table[key]
    # Fallback: kig på scope_type alene
    fallback = {
        _SCOPE_WHOLE:    0.80,
        _SCOPE_AREA:     0.40,
        _SCOPE_UNKNOWN:  0.10,
    }
    return fallback.get(scope_type, 0.10)


def resolve_scope(
    entries: List[Servitut],
    case_matrikler: List[str],
    primary_parcel: Optional[str] = None,
) -> List[Servitut]:
    """Resolvér scope for alle entries.

    Opdaterer in-place via model_copy og returnerer den ny liste.
    """
    resolved: List[Servitut] = []
    for entry in entries:
        scope_text = (entry.raw_scope_text or "") + " " + " ".join(entry.raw_parcel_references)

        # Klassificér scope_type
        if _is_whole_property(scope_text):
            scope_type = _SCOPE_WHOLE
            match_quality = "any"
            matched_parcels = list(case_matrikler)  # gælder alle
        else:
            raw_refs = _extract_parcel_refs(scope_text)
            if raw_refs:
                scope_type = _SCOPE_EXPLICIT
                matched_parcels, match_quality = _match_parcels(raw_refs, case_matrikler)
            elif _has_area_signal(scope_text):
                scope_type = _SCOPE_AREA
                match_quality = "with_signal"
                matched_parcels = []
            elif scope_text.strip():
                scope_type = _SCOPE_AREA
                match_quality = "no_signal"
                matched_parcels = []
            else:
                scope_type = _SCOPE_UNKNOWN
                match_quality = "any"
                matched_parcels = []

        # Beregn confidence
        is_fanout_inherited = entry.is_fanout_entry and not _extract_parcel_refs(scope_text)
        confidence = _scope_confidence(scope_type, match_quality, is_fanout_inherited)

        # Bevar allerede sat confidence fra fanout (0.75 for egne refs, 0.35 arvet)
        # kun hvis scope_resolver ikke har bedre information
        if entry.scope_confidence and entry.scope_confidence > 0 and scope_type == _SCOPE_UNKNOWN:
            confidence = entry.scope_confidence

        applies_to_primary = False
        if primary_parcel and matched_parcels:
            applies_to_primary = _normalize_parcel(primary_parcel) in {
                _normalize_parcel(p) for p in matched_parcels
            }

        # Flags
        flags = list(entry.flags)
        if confidence < REVIEW_THRESHOLD and "review_required" not in flags:
            flags.append("review_required")

        resolved.append(
            entry.model_copy(
                update={
                    "scope_type": scope_type,
                    "scope_confidence": confidence,
                    "applies_to_parcel_numbers": matched_parcels,
                    "applies_to_primary_parcel": applies_to_primary,
                    "flags": flags,
                }
            )
        )

    return resolved
