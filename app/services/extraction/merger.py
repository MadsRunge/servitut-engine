from typing import List

from app.core.logging import get_logger
from app.models.servitut import Servitut
from app.services.extraction.matching import _extract_date_components, _servitut_matches

logger = get_logger(__name__)


def _enrich_canonical(canonical: Servitut, akt_srv: Servitut) -> Servitut:
    """Berig canonical servitut med detaljer fra akt."""
    canonical_has_scope = any(
        [
            canonical.applies_to_parcel_numbers,
            canonical.raw_parcel_references,
            canonical.raw_scope_text,
        ]
    )
    updates: dict = {
        "confidence": max(canonical.confidence, akt_srv.confidence),
        "evidence": canonical.evidence + akt_srv.evidence,
        "source_document": akt_srv.source_document,
        "registered_at": canonical.registered_at or akt_srv.registered_at,
    }

    if akt_srv.archive_number:
        updates["archive_number"] = akt_srv.archive_number
    if akt_srv.summary:
        updates["summary"] = akt_srv.summary
    if akt_srv.beneficiary:
        updates["beneficiary"] = akt_srv.beneficiary
    if akt_srv.disposition_type:
        updates["disposition_type"] = akt_srv.disposition_type
    if akt_srv.legal_type:
        updates["legal_type"] = akt_srv.legal_type
    if akt_srv.action_note:
        updates["action_note"] = akt_srv.action_note
    if akt_srv.construction_impact:
        updates["construction_impact"] = akt_srv.construction_impact
    if akt_srv.construction_relevance:
        updates["construction_relevance"] = True
    # Attest-scope er source of truth. Akt må kun udfylde scope hvis canonical mangler
    # eksplicit scope-evidens.
    if not canonical_has_scope:
        if akt_srv.applies_to_parcel_numbers:
            updates["applies_to_parcel_numbers"] = akt_srv.applies_to_parcel_numbers
        if akt_srv.raw_parcel_references:
            updates["raw_parcel_references"] = akt_srv.raw_parcel_references
        if akt_srv.raw_scope_text:
            updates["raw_scope_text"] = akt_srv.raw_scope_text
        if akt_srv.scope_source:
            updates["scope_source"] = akt_srv.scope_source
        if akt_srv.applies_to_primary_parcel is not None:
            updates["applies_to_primary_parcel"] = akt_srv.applies_to_primary_parcel
        if akt_srv.scope_basis:
            updates["scope_basis"] = akt_srv.scope_basis
        if akt_srv.scope_confidence is not None:
            updates["scope_confidence"] = akt_srv.scope_confidence
    elif not canonical.scope_source:
        updates["scope_source"] = "attest"

    return canonical.model_copy(update=updates)


def _dedup_akt_servitutter(akt_list: List[Servitut]) -> List[Servitut]:
    """
    Dedupliker akt-udtrukte servitutter når ingen tinglysningsattest foreligger.
    Grupper på løbenummer/dato og behold den mest komplette per gruppe.
    """
    result: List[Servitut] = []
    used = set()

    for i, srv in enumerate(akt_list):
        if i in used:
            continue
        matches = [
            j
            for j, other in enumerate(akt_list)
            if j != i and j not in used and _servitut_matches(srv, other)
        ]
        if matches:
            group = [srv] + [akt_list[j] for j in matches]
            best = max(
                group,
                key=lambda s: (
                    sum(
                        1
                        for f in [
                            s.beneficiary,
                            s.summary,
                            s.disposition_type,
                            s.legal_type,
                            s.action_note,
                        ]
                        if f
                    ),
                    s.confidence,
                ),
            )
            result.append(best)
            used.update(matches)
        else:
            result.append(srv)
        used.add(i)

    logger.info(f"Dedup (fallback): {len(akt_list)} → {len(result)} servitutter")
    return result


def _merge_servitutter(
    canonical_list: List[Servitut], akt_list: List[Servitut]
) -> List[Servitut]:
    """
    Brug canonical_list (fra tinglysningsattest) som source of truth.
    Berig hvert canonical entry med bedste match fra akt_list.
    Akt-servitutter uden canonical match kasseres.
    """
    canonical_years: dict[str, int] = {}
    for canonical in canonical_list:
        components = _extract_date_components(canonical.date_reference)
        if components.get("year"):
            year = components["year"]
            canonical_years[year] = canonical_years.get(year, 0) + 1

    result = []
    for canonical in canonical_list:
        matches = [
            akt_srv
            for akt_srv in akt_list
            if _servitut_matches(canonical, akt_srv, canonical_years)
        ]
        if matches:
            best = max(matches, key=lambda srv: srv.confidence)
            result.append(_enrich_canonical(canonical, best))
            logger.debug(f"Match: {canonical.date_reference} ← {best.source_document}")
        else:
            result.append(canonical)

    discarded = len(akt_list) - sum(
        1
        for akt_srv in akt_list
        if any(_servitut_matches(canonical, akt_srv, canonical_years) for canonical in canonical_list)
    )
    logger.info(f"Merge færdig: {len(result)} servitutter, {discarded} duplikater kasseret")
    return result
