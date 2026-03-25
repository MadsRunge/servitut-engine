from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.dependencies.auth import get_current_user
from app.core.logging import get_logger
from app.db.database import get_session
from app.models.declaration import DeclarationPatch, Servituterklaring
from app.models.user import User
from app.services import case_service, storage_service
from app.services.declaration_service import generate_declaration

logger = get_logger(__name__)

router = APIRouter()


@router.post("/{case_id}/declarations", response_model=Servituterklaring, status_code=201)
def create_declaration(
    case_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case = case_service.verify_case_ownership(session, case_id, current_user.id)
    case = case_service.sync_case_matrikler(
        session,
        case_id,
        owner_user_id=current_user.id,
    ) or case

    servitutter = storage_service.list_servitutter(
        session,
        case_id,
        owner_user_id=current_user.id,
    )
    servitutter = [srv for srv in servitutter if srv.confirmed_by_attest]
    if not servitutter:
        raise HTTPException(
            status_code=400,
            detail="No servitutter found — run extraction first",
        )

    target = [case.primary_parcel_number] if case.primary_parcel_number else []
    available = [m.parcel_number for m in case.parcels]

    try:
        decl = generate_declaration(
            session,
            servitutter,
            case_id,
            target_parcel_numbers=target,
            available_parcel_numbers=available,
        )
    except Exception:
        logger.exception("Fejl ved generering af servituterklæring for sag %s", case_id)
        raise HTTPException(status_code=500, detail="Kunne ikke oprette servituterklæring")

    storage_service.save_declaration(session, decl)
    return decl


@router.get("/{case_id}/declarations", response_model=List[Servituterklaring])
def list_declarations(
    case_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    return storage_service.list_declarations(
        session,
        case_id,
        owner_user_id=current_user.id,
    )


@router.patch("/{case_id}/declarations/{declaration_id}", response_model=Servituterklaring)
def patch_declaration(
    case_id: str,
    declaration_id: str,
    body: DeclarationPatch,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    decl = storage_service.load_declaration(
        session,
        case_id,
        declaration_id,
        owner_user_id=current_user.id,
    )
    if not decl:
        raise HTTPException(status_code=404, detail="Declaration not found")

    rows = decl.rows
    if body.rows:
        row_map = {r.easement_id: r for r in rows}
        for rp in body.rows:
            if rp.easement_id in row_map:
                updates = {}
                if rp.review_status is not None:
                    updates["review_status"] = rp.review_status
                if rp.remarks is not None:
                    updates["remarks"] = rp.remarks
                if updates:
                    row_map[rp.easement_id] = row_map[rp.easement_id].model_copy(update=updates)
        rows = list(row_map.values())

        # Sync manual review edits back to the underlying Servitut records so
        # the servitut profile and declaration tab stay consistent after manual overrides.
        patched_ids = {
            rp.easement_id
            for rp in body.rows
            if rp.review_status is not None or rp.remarks is not None
        }
        if patched_ids:
            servitutter = storage_service.list_servitutter(
                session, case_id, owner_user_id=current_user.id
            )
            srv_map = {s.easement_id: s for s in servitutter}
            for rp in body.rows:
                srv = srv_map.get(rp.easement_id)
                if srv is None or (rp.review_status is None and rp.remarks is None):
                    continue
                srv_updates: dict = {}
                if rp.review_status is not None:
                    srv_updates["review_status"] = rp.review_status  # ReviewStatus is str
                if rp.remarks is not None:
                    srv_updates["review_remarks"] = rp.remarks
                storage_service.save_servitut(
                    session, srv.model_copy(update=srv_updates), commit=False
                )

    updated = decl.model_copy(update={
        "rows": rows,
        "notes": body.notes if body.notes is not None else decl.notes,
        "manually_reviewed": True,
    })
    storage_service.save_declaration(session, updated)  # single commit point
    return updated


@router.get("/{case_id}/declarations/{declaration_id}", response_model=Servituterklaring)
def get_declaration(
    case_id: str,
    declaration_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    case_service.verify_case_ownership(session, case_id, current_user.id)
    decl = storage_service.load_declaration(
        session,
        case_id,
        declaration_id,
        owner_user_id=current_user.id,
    )
    if not decl:
        raise HTTPException(status_code=404, detail="Declaration not found")
    return decl
