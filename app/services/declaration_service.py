"""
Service der bygger en Servituterklæring fra en sags servitutter.

Erklæringen er deterministisk (ingen LLM-kald). Den kopierer relevante felter
fra hver Servitut og tildeler en reviewstatus baseret på eksisterende
kvalitetsfelter.

Reviewfelter persisteres OGSÅ direkte på Servitut (review_status, review_remarks),
så status er tilgængelig på servitutniveau uafhængigt af erklæringen. Scope-
afhængige statuser (historisk_matrikel) kræver erklæringskonteksten og gemmes
kun på ServituterklaeringRow.
"""

from datetime import date, datetime
from typing import List, Optional, Tuple

from sqlmodel import Session

from app.core.logging import get_logger
from app.models.declaration import (
    ReviewStatus,
    Servituterklaring,
    ServituterklaeringRow,
)
from app.models.servitut import Servitut
from app.services import matrikel_service, storage_service
from app.utils.ids import generate_declaration_id

logger = get_logger(__name__)


def _parse_date_reference(date_ref: Optional[str]) -> date:
    """Returnerer date.max for None/ugyldige datoer → sorteres sidst."""
    if not date_ref:
        return date.max
    try:
        return datetime.strptime(date_ref[:10], "%d.%m.%Y").date()
    except ValueError:
        return date.max


def _scope_label(applies_to_primary: Optional[bool]) -> Optional[str]:
    if applies_to_primary is True:
        return "Ja"
    if applies_to_primary is False:
        return "Nej"
    return "Måske"


def compute_servitut_review_status(srv: Servitut) -> Tuple[str, str]:
    """
    Beregner (review_status, review_remarks) udelukkende fra servituttens
    egne felter — uden afhængighed af målmatrikel/scope.

    Kan kaldes fra eksternt (f.eks. extraction_service) for at persistere
    reviewstate pr. servitut uden at generere en fuld erklæring.

    Returnerer streng-værdier (ikke ReviewStatus enum) for nem persistering.
    """
    status, remarks = _compute_review_status_standalone(srv)
    return status.value, remarks


def _compute_review_status_standalone(srv: Servitut) -> Tuple[ReviewStatus, str]:
    """
    Scope-uafhængig reviewstatus. `historisk_matrikel` udelades her fordi
    den kræver kendskab til kendte matrikelnumre (tilgængeligt først ved
    erklæringsgenerering).
    """
    if not srv.evidence:
        return ReviewStatus.mangler_kilde, "Ingen evidens fundet for denne servitut."

    if not srv.confirmed_by_attest:
        return ReviewStatus.kun_i_akt, "Fundet i akt, men ikke bekræftet i tinglysningsattest."

    conf = srv.confidence or 0.0
    scope_conf = srv.scope_confidence
    if conf < 0.6 or (scope_conf is not None and scope_conf < 0.5):
        return ReviewStatus.kraever_kontrol, f"Lav konfidenscore ({conf:.0%}) – kræver manuel kontrol."

    return ReviewStatus.klar, ""


def _compute_review_status(
    srv: Servitut,
    scope_result: Optional[bool],
) -> Tuple[ReviewStatus, str]:
    """
    Scope-bevidst reviewstatus til brug i erklæringsrækker.

    Prioritetsrækkefølge (første match vinder):
    1. mangler_kilde      — ingen evidens
    2. kun_i_akt          — ikke bekræftet i attest
    3. historisk_matrikel — ukendt matrikelnummer i scope (kræver scope_result)
    4. kraever_kontrol    — lav konfidenscore
    5. klar               — ingen kendte problemer
    """
    status, remarks = _compute_review_status_standalone(srv)
    if status != ReviewStatus.klar:
        return status, remarks

    # Tilføj historisk_matrikel-check med scope-kontekst
    if scope_result is None and srv.raw_parcel_references:
        return (
            ReviewStatus.historisk_matrikel,
            "Historisk matrikelnummer – uafklaret om gælder nuværende matrikel.",
        )

    return ReviewStatus.klar, ""


def generate_declaration(
    session: Session,
    servitutter: List[Servitut],
    case_id: str,
    target_parcel_numbers: List[str],
    available_parcel_numbers: List[str],
) -> Servituterklaring:
    """
    Bygger en Servituterklæring fra eksisterende servitutter.

    Som bieffekt persisteres review_status og review_remarks direkte på hver
    Servitut i DB'en (scope-uafhængig version), så reviewstate er tilgængeligt
    på servitutniveau uden at hente erklæringen.
    """
    # Annotér applies_to_primary_parcel dynamisk for det valgte målsæt
    annotated = matrikel_service.filter_servitutter_for_target(
        servitutter,
        target_parcel_numbers,
        available_parcel_numbers,
    )

    # Sorter pr. dato (ukendte datoer sidst)
    annotated = sorted(annotated, key=lambda s: _parse_date_reference(s.date_reference))

    rows: List[ServituterklaeringRow] = []
    for i, srv in enumerate(annotated, 1):
        scope_result = srv.applies_to_primary_parcel
        # Scope-bevidst status til erklæringsrækken
        row_status, row_remarks = _compute_review_status(srv, scope_result)
        # Scope-uafhængig status persisteres på selve servitutten
        standalone_status, standalone_remarks = _compute_review_status_standalone(srv)

        rows.append(
            ServituterklaeringRow(
                sequence_number=i,
                easement_id=srv.easement_id,
                priority=srv.priority,
                date_reference=srv.date_reference,
                title=srv.title,
                archive_number=srv.archive_number,
                beneficiary=srv.beneficiary,
                remarks=row_remarks,
                applies_to_parcel_numbers=list(srv.applies_to_parcel_numbers),
                review_status=row_status,
                confirmed_by_attest=srv.confirmed_by_attest,
                confidence=srv.confidence,
                scope=_scope_label(scope_result),
            )
        )

        # Stage reviewstate på servitutniveau (scope-uafhængig) — commit=False
        # så alle ændringer indgår i den samme transaktion som save_declaration().
        if srv.review_status != standalone_status.value or srv.review_remarks != standalone_remarks:
            updated = srv.model_copy(update={
                "review_status": standalone_status.value,
                "review_remarks": standalone_remarks,
            })
            storage_service.save_servitut(session, updated, commit=False)

    declaration = Servituterklaring(
        declaration_id=generate_declaration_id(),
        case_id=case_id,
        created_at=datetime.utcnow(),
        target_parcel_numbers=list(target_parcel_numbers),
        rows=rows,
    )

    logger.info(
        f"Generated declaration {declaration.declaration_id} for case {case_id} "
        f"with {len(rows)} rows"
    )
    return declaration
