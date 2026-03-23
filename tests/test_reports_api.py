"""Tests for Report API endpoints — create, fetch, and PATCH."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.core.config import settings
from app.db.database import create_tables, get_session_ctx, reset_engine_cache
from app.models.case import Matrikel
from app.models.report import Report, ReportEntry
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
        case.primary_parcel_number = "1a"
        case.parcels = [Matrikel(parcel_number="1a", cadastral_district="Testjorder")]
        storage_service.save_case(session, case)
        token = build_access_token(user)
    return case, {"Authorization": f"Bearer {token}"}


def _make_report(case_id: str) -> Report:
    return Report(
        report_id="rep-test1",
        case_id=case_id,
        target_parcel_numbers=["1a"],
        available_parcel_numbers=["1a"],
        entries=[
            ReportEntry(
                sequence_number=1,
                date_reference="15.06.2000-1000",
                title="Vejret",
                description="Vejret over ejendommen",
                beneficiary="Kommunen",
                action="behold",
                relevant_for_project=True,
                easement_id="srv-1",
            ),
            ReportEntry(
                sequence_number=2,
                date_reference="01.01.1990-2000",
                title="Kloakservitut",
                description="Kloakledning",
                beneficiary="Forsyningen",
                action="afklar",
                relevant_for_project=False,
                easement_id="srv-2",
            ),
        ],
        notes="Original note",
    )


def test_patch_report_updates_entries_and_rebuilds_markdown():
    case, headers = _create_case_with_headers("rep-patch@example.com", "Rapport-sag")

    with get_session_ctx() as session:
        storage_service.save_report(session, _make_report(case.case_id))

    updated_entries = [
        {
            "sequence_number": 1,
            "date_reference": "15.06.2000-1000",
            "title": "Vejret (opdateret)",
            "description": "Revideret beskrivelse",
            "beneficiary": "Kommunen",
            "action": "behold",
            "relevant_for_project": True,
            "easement_id": "srv-1",
        },
        {
            "sequence_number": 2,
            "date_reference": "01.01.1990-2000",
            "title": "Kloakservitut",
            "description": "Kloakledning",
            "beneficiary": "Forsyningen",
            "action": "afklar",
            "relevant_for_project": False,
            "easement_id": "srv-2",
        },
    ]

    response = client.patch(
        f"/cases/{case.case_id}/reports/rep-test1",
        json={"entries": updated_entries},
        headers=headers,
    )

    assert response.status_code == 200
    patched = response.json()
    assert patched["manually_edited"] is True
    assert patched["edited_at"] is not None

    titles = [e["title"] for e in patched["entries"]]
    assert "Vejret (opdateret)" in titles

    # markdown_content should be rebuilt and include the updated title
    assert patched["markdown_content"] is not None
    assert "Vejret (opdateret)" in patched["markdown_content"]

    # Notes untouched when not sent
    assert patched["notes"] == "Original note"


def test_patch_report_updates_notes_only():
    case, headers = _create_case_with_headers("rep-notes@example.com", "Notes-sag")

    with get_session_ctx() as session:
        storage_service.save_report(session, _make_report(case.case_id))

    response = client.patch(
        f"/cases/{case.case_id}/reports/rep-test1",
        json={"notes": "Tilføjet faglig note"},
        headers=headers,
    )

    assert response.status_code == 200
    patched = response.json()
    assert patched["notes"] == "Tilføjet faglig note"
    assert patched["manually_edited"] is True

    # Entries should be unchanged
    assert len(patched["entries"]) == 2
    assert patched["entries"][0]["title"] == "Vejret"


def test_patch_report_not_found():
    case, headers = _create_case_with_headers("rep-404@example.com", "Manglende rapport")

    response = client.patch(
        f"/cases/{case.case_id}/reports/rep-nonexistent",
        json={"notes": "test"},
        headers=headers,
    )
    assert response.status_code == 404


def test_patch_report_forbidden_for_foreign_user():
    case, _ = _create_case_with_headers("rep-owner@example.com", "Ejet rapport-sag")
    _, viewer_headers = _create_case_with_headers("rep-viewer@example.com", "Fremmed bruger")

    with get_session_ctx() as session:
        storage_service.save_report(session, _make_report(case.case_id))

    response = client.patch(
        f"/cases/{case.case_id}/reports/rep-test1",
        json={"notes": "Ulovlig adgang"},
        headers=viewer_headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
