import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.core.config import settings
from app.db.database import create_tables, get_session_ctx, reset_engine_cache
from app.models.case import Matrikel
from app.models.servitut import Evidence, Servitut
from app.services import storage_service
from app.services.auth_service import build_access_token, create_user
from app.services.case_service import create_case

client = TestClient(app)


@pytest.fixture(autouse=True)
def db_env(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    (tmp_path / "cases").mkdir()
    reset_engine_cache()
    create_tables()
    yield tmp_path
    reset_engine_cache()


def _create_case_with_headers(email: str, name: str):
    with get_session_ctx() as session:
        user = create_user(session, email=email, password="secret123")
        case = create_case(session, name=name, user_id=user.id)
        case.primary_parcel_number = "5adl"
        case.parcels = [
            Matrikel(parcel_number="5adl", cadastral_district="Aalborg Markjorder"),
            Matrikel(parcel_number="3r", cadastral_district="Aalborg Markjorder"),
        ]
        storage_service.save_case(session, case)
        token = build_access_token(user)
    return case, {"Authorization": f"Bearer {token}"}


def test_create_declaration_persists_snapshot_and_review_fields():
    case, headers = _create_case_with_headers("decl-owner@example.com", "Erklæringssag")

    with get_session_ctx() as session:
        storage_service.save_servitut(
            session,
            Servitut(
                easement_id="srv-missing-evidence",
                case_id=case.case_id,
                source_document="attest-1",
                priority=2,
                date_reference="25.06.2019-1010869578",
                archive_number="akt-1",
                title="Statsekspropriation",
                beneficiary="Aalborg Kommune",
                applies_to_parcel_numbers=["5adl"],
                confirmed_by_attest=True,
                confidence=0.92,
                evidence=[],
            ),
        )
        storage_service.save_servitut(
            session,
            Servitut(
                easement_id="srv-historical",
                case_id=case.case_id,
                source_document="akt-2",
                priority=1,
                date_reference="24.04.1897-963835-76",
                archive_number="akt-2",
                title="Dok om vej mv",
                beneficiary="Privat påtale",
                applies_to_parcel_numbers=["960b"],
                raw_parcel_references=["960b"],
                confirmed_by_attest=True,
                confidence=0.91,
                evidence=[
                    Evidence(
                        chunk_id="chunk-1",
                        document_id="akt-2",
                        page=3,
                        text_excerpt="Dok om vej mv(23/713), -",
                    )
                ],
            ),
        )

    response = client.post(f"/cases/{case.case_id}/declarations", headers=headers)

    assert response.status_code == 201
    payload = response.json()
    assert payload["case_id"] == case.case_id
    assert len(payload["rows"]) == 2
    assert [row["easement_id"] for row in payload["rows"]] == [
        "srv-historical",
        "srv-missing-evidence",
    ]
    assert payload["rows"][0]["review_status"] == "historisk_matrikel"
    assert "Historisk matrikelnummer" in payload["rows"][0]["remarks"]
    assert payload["rows"][1]["review_status"] == "mangler_kilde"

    list_response = client.get(f"/cases/{case.case_id}/declarations", headers=headers)
    assert list_response.status_code == 200
    declarations = list_response.json()
    assert len(declarations) == 1
    declaration_id = declarations[0]["declaration_id"]

    get_response = client.get(
        f"/cases/{case.case_id}/declarations/{declaration_id}",
        headers=headers,
    )
    assert get_response.status_code == 200
    assert get_response.json()["declaration_id"] == declaration_id

    with get_session_ctx() as session:
        persisted_missing = storage_service.load_servitut(
            session,
            case.case_id,
            "srv-missing-evidence",
        )
        persisted_historical = storage_service.load_servitut(
            session,
            case.case_id,
            "srv-historical",
        )

    assert persisted_missing is not None
    assert persisted_missing.review_status == "mangler_kilde"
    assert "Ingen evidens" in (persisted_missing.review_remarks or "")

    assert persisted_historical is not None
    assert persisted_historical.review_status == "klar"
    assert persisted_historical.review_remarks == ""


def test_create_declaration_ignores_non_attest_servitutter():
    case, headers = _create_case_with_headers("decl-filter@example.com", "Filter-sag")

    with get_session_ctx() as session:
        storage_service.save_servitut(
            session,
            Servitut(
                easement_id="srv-confirmed",
                case_id=case.case_id,
                source_document="attest-1",
                priority=1,
                title="Bekræftet servitut",
                confirmed_by_attest=True,
                confidence=0.95,
                evidence=[
                    Evidence(
                        chunk_id="chunk-confirmed",
                        document_id="attest-1",
                        page=1,
                        text_excerpt="Bekræftet tekst",
                    )
                ],
            ),
        )
        storage_service.save_servitut(
            session,
            Servitut(
                easement_id="srv-unconfirmed",
                case_id=case.case_id,
                source_document="akt-1",
                priority=2,
                title="Kun i akt",
                confirmed_by_attest=False,
                confidence=0.95,
                evidence=[
                    Evidence(
                        chunk_id="chunk-unconfirmed",
                        document_id="akt-1",
                        page=2,
                        text_excerpt="Kun i akt tekst",
                    )
                ],
            ),
        )

    response = client.post(f"/cases/{case.case_id}/declarations", headers=headers)

    assert response.status_code == 201
    payload = response.json()
    assert [row["easement_id"] for row in payload["rows"]] == ["srv-confirmed"]


def test_patch_declaration_updates_row_and_syncs_servitut():
    """PATCH updates the declaration snapshot AND propagates to Servitut.review_status."""
    case, headers = _create_case_with_headers("decl-patch@example.com", "Patch-sag")

    with get_session_ctx() as session:
        storage_service.save_servitut(
            session,
            Servitut(
                easement_id="srv-to-patch",
                case_id=case.case_id,
                source_document="akt-1",
                priority=1,
                title="Vejret",
                confirmed_by_attest=True,
                confidence=0.95,
                evidence=[],  # no evidence → mangler_kilde
            ),
        )

    create_resp = client.post(f"/cases/{case.case_id}/declarations", headers=headers)
    assert create_resp.status_code == 201
    decl_id = create_resp.json()["declaration_id"]
    initial_row = next(r for r in create_resp.json()["rows"] if r["easement_id"] == "srv-to-patch")
    assert initial_row["review_status"] == "mangler_kilde"

    patch_resp = client.patch(
        f"/cases/{case.case_id}/declarations/{decl_id}",
        json={"rows": [{"easement_id": "srv-to-patch", "review_status": "klar", "remarks": "Verificeret manuelt"}]},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["manually_reviewed"] is True

    patched_row = next(r for r in patched["rows"] if r["easement_id"] == "srv-to-patch")
    assert patched_row["review_status"] == "klar"
    assert patched_row["remarks"] == "Verificeret manuelt"

    # Verify that the underlying Servitut is also synced
    with get_session_ctx() as session:
        srv = storage_service.load_servitut(session, case.case_id, "srv-to-patch")
    assert srv is not None
    assert srv.review_status == "klar"
    assert srv.review_remarks == "Verificeret manuelt"


def test_patch_declaration_notes_only():
    """PATCH with only notes leaves rows unchanged."""
    case, headers = _create_case_with_headers("decl-notes@example.com", "Notes-sag")

    with get_session_ctx() as session:
        storage_service.save_servitut(
            session,
            Servitut(
                easement_id="srv-notes",
                case_id=case.case_id,
                source_document="akt-1",
                confirmed_by_attest=True,
                confidence=0.9,
                evidence=[Evidence(chunk_id="c1", document_id="akt-1", page=1, text_excerpt="tekst")],
            ),
        )

    create_resp = client.post(f"/cases/{case.case_id}/declarations", headers=headers)
    assert create_resp.status_code == 201
    decl_id = create_resp.json()["declaration_id"]
    original_rows = create_resp.json()["rows"]

    patch_resp = client.patch(
        f"/cases/{case.case_id}/declarations/{decl_id}",
        json={"notes": "Gennemgået 2026-03-23"},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["notes"] == "Gennemgået 2026-03-23"
    assert patched["manually_reviewed"] is True
    assert patched["rows"] == original_rows  # rows untouched


def test_patch_declaration_not_found():
    case, headers = _create_case_with_headers("decl-404@example.com", "404-sag")

    response = client.patch(
        f"/cases/{case.case_id}/declarations/dec-nonexistent",
        json={"rows": []},
        headers=headers,
    )
    assert response.status_code == 404


def test_declaration_routes_forbid_foreign_case_access():
    case, _ = _create_case_with_headers("decl-owner2@example.com", "Ejet sag")
    _, viewer_headers = _create_case_with_headers("decl-viewer@example.com", "Fremmed bruger")

    for method, path in [
        ("POST", f"/cases/{case.case_id}/declarations"),
        ("GET", f"/cases/{case.case_id}/declarations"),
        ("GET", f"/cases/{case.case_id}/declarations/dec-foreign"),
    ]:
        response = client.request(method, path, headers=viewer_headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"
        assert response.json()["error"]["message"] == "Forbidden"

    # PATCH requires a body — test separately
    patch_response = client.patch(
        f"/cases/{case.case_id}/declarations/dec-foreign",
        json={"rows": []},
        headers=viewer_headers,
    )
    assert patch_response.status_code == 403
    assert patch_response.json()["error"]["code"] == "forbidden"
