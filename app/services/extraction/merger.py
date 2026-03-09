from typing import List

from app.core.logging import get_logger
from app.models.servitut import Servitut
from app.services.extraction.matching import _extract_date_components, _servitut_matches

logger = get_logger(__name__)


def _enrich_canonical(canonical: Servitut, akt_srv: Servitut) -> Servitut:
    """Berig canonical servitut med detaljer fra akt."""
    updates: dict = {
        "confidence": max(canonical.confidence, akt_srv.confidence),
        "evidence": canonical.evidence + akt_srv.evidence,
        "source_document": akt_srv.source_document,
    }

    if akt_srv.akt_nr:
        updates["akt_nr"] = akt_srv.akt_nr
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
    if akt_srv.byggeri_markering:
        updates["byggeri_markering"] = akt_srv.byggeri_markering
    if akt_srv.construction_relevance:
        updates["construction_relevance"] = True
    # Attest-scope (canonical.applies_to_matrikler) er ground truth — overskriv ikke.
    # Brug kun akt-LLM's scope hvis attesten ikke har angivet noget.
    if akt_srv.applies_to_matrikler and not canonical.applies_to_matrikler:
        updates["applies_to_matrikler"] = akt_srv.applies_to_matrikler
        if akt_srv.applies_to_target_matrikel is not None:
            updates["applies_to_target_matrikel"] = akt_srv.applies_to_target_matrikel
        if akt_srv.scope_basis:
            updates["scope_basis"] = akt_srv.scope_basis
        if akt_srv.scope_confidence is not None:
            updates["scope_confidence"] = akt_srv.scope_confidence

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
