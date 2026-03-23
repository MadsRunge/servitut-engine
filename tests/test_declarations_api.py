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
